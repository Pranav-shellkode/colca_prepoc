import json

import psycopg

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

_INSERT_SQL = f"""
INSERT INTO {TABLE_NAME} (session_id, started_at, ended_at, transcript, summary)
VALUES (%s, %s, %s, %s, %s);
"""


def save_call_summary(
    session_id: str,
    started_at: str,
    ended_at: str,
    transcript: str,
    summary: dict,
) -> None:
    """Persist a call's transcript and structured summary to Postgres."""
    with psycopg.connect(_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TABLE_SQL)
            cur.execute(
                _INSERT_SQL,
                (session_id, started_at, ended_at, transcript, json.dumps(summary)),
            )
        conn.commit()

