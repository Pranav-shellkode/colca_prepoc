import json

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
UPDATE {TABLE_NAME} SET call_id = session_id WHERE call_id IS NULL;
ALTER TABLE {TABLE_NAME} ALTER COLUMN call_id SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS call_summaries_call_id_key ON {TABLE_NAME} (call_id);
"""

_INSERT_SQL = f"""
INSERT INTO {TABLE_NAME}
    (call_id, session_id, phone_number, lead_context, started_at, ended_at, transcript, summary, outcome)
VALUES
    (%s, %s, %s, %s, %s, %s, %s, %s, %s);
"""

_SELECT_BY_CALL_ID_SQL = f"""
SELECT call_id, session_id, phone_number, lead_context, started_at, ended_at,
       transcript, summary, outcome, created_at
FROM {TABLE_NAME}
WHERE call_id = %s;
"""

_SELECT_LIST_SQL = f"""
SELECT call_id, phone_number, lead_context, started_at, ended_at, outcome, created_at
FROM {TABLE_NAME}
ORDER BY created_at DESC
LIMIT %s;
"""


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
                _INSERT_SQL,
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