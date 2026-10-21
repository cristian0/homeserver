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
        status IN ('planned', 'immediate_done', 'complete', 'superseded', 'skipped')
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
    morning_saved_at TEXT,
    completed_at TEXT,
    superseded_at TEXT,
    superseded_by_id TEXT REFERENCES sessions(id),
    skipped_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_session
ON sessions ((1))
WHERE status IN ('planned', 'immediate_done');

CREATE INDEX IF NOT EXISTS sessions_sequence
ON sessions (sequence_number, imported_at);

CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'plan' CHECK (kind IN ('plan', 'skip')),
    plan_json TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'discarded')),
    decided_at TEXT,
    session_id TEXT REFERENCES sessions(id),
    target_session_id TEXT REFERENCES sessions(id),
    CHECK (
        (kind = 'plan' AND plan_json IS NOT NULL AND target_session_id IS NULL)
        OR (kind = 'skip' AND plan_json IS NULL AND target_session_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS one_pending_proposal
ON plan_proposals ((1))
WHERE status = 'pending';
