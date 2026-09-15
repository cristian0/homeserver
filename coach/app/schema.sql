CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    sequence_number INTEGER NOT NULL CHECK (sequence_number >= 1),
    title TEXT NOT NULL,
    activity_type TEXT NOT NULL CHECK (
        activity_type IN ('complete', 'mobility', 'walk', 'rest', 'combined')
    ),
    estimated_minutes INTEGER NOT NULL CHECK (
        estimated_minutes BETWEEN 0 AND 180
    ),
    status TEXT NOT NULL CHECK (
        status IN ('planned', 'immediate_done', 'complete', 'superseded')
    ),
    pre_operational INTEGER NOT NULL CHECK (pre_operational IN (0, 1)),
    plan_json TEXT NOT NULL,
    completion_json TEXT NOT NULL DEFAULT '[]',
    immediate_feedback_json TEXT,
    next_morning_feedback_json TEXT,
    coach_summary_text TEXT,
    imported_at TEXT NOT NULL,
    started_at TEXT,
    immediate_saved_at TEXT,
    completed_at TEXT,
    superseded_at TEXT,
    superseded_by_id TEXT REFERENCES sessions(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_session
ON sessions ((1))
WHERE status IN ('planned', 'immediate_done');

CREATE INDEX IF NOT EXISTS sessions_sequence
ON sessions (sequence_number, imported_at);
