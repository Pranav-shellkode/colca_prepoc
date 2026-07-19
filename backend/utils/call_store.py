import json
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from backend.core.config import POSTGRES_URL

TABLE_NAME = "call_summaries"

_DSN = POSTGRES_URL.replace("postgresql+psycopg://", "postgresql://")

_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL,
    transcript TEXT NOT NULL,
    summary JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# Migrates a pre-existing table (from before call_id/outcome/etc. were added)
# without dropping data. Backfills call_id from session_id for old rows so
# the NOT NULL + UNIQUE constraint can be applied safely.
_MIGRATE_TABLE_SQL = f"""
ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS call_id TEXT;
ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS phone_number TEXT;
ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS lead_context JSONB;
ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS outcome TEXT;
ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS telco_status TEXT;
ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS telco_code TEXT;
ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS call_duration_secs INTEGER;
UPDATE {TABLE_NAME} SET call_id = session_id WHERE call_id IS NULL;
ALTER TABLE {TABLE_NAME} ALTER COLUMN call_id SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS call_summaries_call_id_key ON {TABLE_NAME} (call_id);
"""

# Upsert used by the pipeline's own summary save (backend/pipecat/pipeline.py
# on_client_disconnected). Uses ON CONFLICT rather than a plain INSERT because
# a telephony callback (Ozonetel's /ozonetel/callback, which has no LLM step
# and so is fast) can race ahead of this save and insert a CDR-only
# placeholder row for the same call_id first. Without the upsert, this INSERT
# would then hit the call_id UNIQUE constraint and lose the real summary
# (only caught by a broad except in the caller, so it'd fail silently).
# telco_status/telco_code/call_duration_secs are deliberately left out of the
# SET clause so a CDR the callback already recorded isn't overwritten here.
_UPSERT_SUMMARY_SQL = f"""
INSERT INTO {TABLE_NAME}
    (call_id, session_id, phone_number, lead_context, started_at, ended_at, transcript, summary, outcome)
VALUES
    (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (call_id) DO UPDATE SET
    session_id = EXCLUDED.session_id,
    phone_number = COALESCE(EXCLUDED.phone_number, {TABLE_NAME}.phone_number),
    lead_context = COALESCE(EXCLUDED.lead_context, {TABLE_NAME}.lead_context),
    started_at = EXCLUDED.started_at,
    ended_at = EXCLUDED.ended_at,
    transcript = EXCLUDED.transcript,
    summary = EXCLUDED.summary,
    outcome = EXCLUDED.outcome;
"""

# Upsert used immediately on client disconnect, before the slow AI-summary
# step (summarize_call is a Bedrock round trip, typically 15-20s). Only
# touches the columns known right away (transcript, call basics) — outcome
# and summary are left alone so this can't clobber a real summary that
# save_call_summary already wrote, nor an outcome the /ozonetel/callback CDR
# race already set. save_call_summary's own upsert fills in outcome/summary
# once the AI summary is ready.
_UPSERT_PENDING_SQL = f"""
INSERT INTO {TABLE_NAME}
    (call_id, session_id, phone_number, lead_context, started_at, ended_at, transcript, summary)
VALUES
    (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (call_id) DO UPDATE SET
    session_id = EXCLUDED.session_id,
    phone_number = COALESCE(EXCLUDED.phone_number, {TABLE_NAME}.phone_number),
    lead_context = COALESCE(EXCLUDED.lead_context, {TABLE_NAME}.lead_context),
    started_at = EXCLUDED.started_at,
    ended_at = EXCLUDED.ended_at,
    transcript = EXCLUDED.transcript;
"""

# Upsert used by the /ozonetel/callback webhook. Inserts a CDR-only row when
# the pipeline never saved one (e.g. the callee never answered, so no /ws
# session ever ran) — that call would otherwise be invisible in call
# history. When a row already exists (pipeline saved a real transcript and
# summary), only the telco columns are updated — transcript/summary/outcome
# are left untouched.
_UPSERT_CDR_SQL = f"""
INSERT INTO {TABLE_NAME}
    (call_id, session_id, phone_number, lead_context, started_at, ended_at,
     transcript, summary, outcome, telco_status, telco_code, call_duration_secs)
VALUES
    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (call_id) DO UPDATE SET
    telco_status = EXCLUDED.telco_status,
    telco_code = EXCLUDED.telco_code,
    call_duration_secs = EXCLUDED.call_duration_secs;
"""

_SELECT_BY_CALL_ID_SQL = f"""
SELECT call_id, session_id, phone_number, lead_context, started_at, ended_at,
       transcript, summary, outcome, telco_status, telco_code, call_duration_secs, created_at
FROM {TABLE_NAME}
WHERE call_id = %s;
"""

_SELECT_LIST_SQL = f"""
SELECT call_id, phone_number, lead_context, started_at, ended_at, outcome, created_at
FROM {TABLE_NAME}
ORDER BY created_at DESC
LIMIT %s;
"""


def save_pending_call(
    call_id: str,
    session_id: str,
    started_at: str,
    ended_at: str,
    transcript: str,
    phone_number: str | None = None,
    lead_context: dict | None = None,
) -> None:
    """Persist the call's basics right on disconnect, ahead of the AI summary.

    Makes the call show up in `/calls` (with a "Pending" outcome) and give a
    real 200 from `/calls/{id}/insights` immediately, instead of the frontend
    having to poll for up to ~20s while summarize_call talks to Bedrock.
    """
    with psycopg.connect(_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TABLE_SQL)
            cur.execute(_MIGRATE_TABLE_SQL)
            cur.execute(
                _UPSERT_PENDING_SQL,
                (
                    call_id,
                    session_id,
                    phone_number,
                    json.dumps(lead_context) if lead_context is not None else None,
                    started_at,
                    ended_at,
                    transcript,
                    json.dumps({}),
                ),
            )
        conn.commit()


def save_call_summary(
    call_id: str,
    session_id: str,
    started_at: str,
    ended_at: str,
    transcript: str,
    summary: dict,
    phone_number: str | None = None,
    lead_context: dict | None = None,
) -> None:
    """Persist a call's transcript and structured AI summary/outcome to Postgres."""
    with psycopg.connect(_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TABLE_SQL)
            cur.execute(_MIGRATE_TABLE_SQL)
            cur.execute(
                _UPSERT_SUMMARY_SQL,
                (
                    call_id,
                    session_id,
                    phone_number,
                    json.dumps(lead_context) if lead_context is not None else None,
                    started_at,
                    ended_at,
                    transcript,
                    json.dumps(summary),
                    summary.get("outcome"),
                ),
            )
        conn.commit()


def record_ozonetel_cdr(
    call_id: str,
    telco_status: str,
    telco_code: str | None,
    call_duration_secs: int | None,
    phone_number: str | None = None,
    lead_context: dict | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
) -> None:
    """Record Ozonetel's final CDR status for a call.

    Updates just the telco columns if the pipeline already saved a summary
    row for this call_id; inserts a CDR-only placeholder row otherwise (e.g.
    the callee never answered, so no /ws session — and therefore no
    summary — ever ran for this call).
    """
    now = datetime.now(timezone.utc).isoformat()
    with psycopg.connect(_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TABLE_SQL)
            cur.execute(_MIGRATE_TABLE_SQL)
            cur.execute(
                _UPSERT_CDR_SQL,
                (
                    call_id,
                    call_id,  # session_id: no pipeline session_id exists for a CDR-only row
                    phone_number,
                    json.dumps(lead_context) if lead_context is not None else None,
                    started_at or now,
                    ended_at or now,
                    "",
                    json.dumps({}),
                    telco_status,
                    telco_status,
                    telco_code,
                    call_duration_secs,
                ),
            )
        conn.commit()


def get_call_insights(call_id: str) -> dict | None:
    """Fetch AI insights and outcome for a given call_id, or None if not found."""
    with psycopg.connect(_DSN, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TABLE_SQL)
            cur.execute(_MIGRATE_TABLE_SQL)
            cur.execute(_SELECT_BY_CALL_ID_SQL, (call_id,))
            return cur.fetchone()


def list_calls(limit: int = 7) -> list[dict]:
    """List recent calls (lightest fields only) for a history sidebar."""
    with psycopg.connect(_DSN, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TABLE_SQL)
            cur.execute(_MIGRATE_TABLE_SQL)
            cur.execute(_SELECT_LIST_SQL, (limit,))
            return cur.fetchall()
