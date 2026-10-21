CREATE TABLE sessions_new (
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

INSERT INTO sessions_new (
    id, schema_version, sequence_number, title, activity_type,
    estimated_minutes, status, pre_operational, plan_json, completion_json,
    immediate_feedback_json, next_morning_feedback_json, coach_summary_text,
    imported_at, started_at, immediate_saved_at, morning_saved_at,
    completed_at, superseded_at, superseded_by_id
)
SELECT
    id, schema_version, sequence_number, title, activity_type,
    estimated_minutes, status, pre_operational, plan_json, completion_json,
    immediate_feedback_json, next_morning_feedback_json, coach_summary_text,
    imported_at, started_at, immediate_saved_at, morning_saved_at,
    completed_at, superseded_at, superseded_by_id
FROM sessions;

DROP TABLE sessions;

ALTER TABLE sessions_new RENAME TO sessions;

CREATE UNIQUE INDEX one_active_session
ON sessions ((1))
WHERE status IN ('planned', 'immediate_done');

CREATE INDEX sessions_sequence
ON sessions (sequence_number, imported_at);

CREATE TABLE plan_proposals_new (
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

INSERT INTO plan_proposals_new (
    id, created_at, kind, plan_json, status, decided_at, session_id
)
SELECT id, created_at, 'plan', plan_json, status, decided_at, session_id
FROM plan_proposals;

DELETE FROM sqlite_sequence WHERE name = 'plan_proposals_new';

INSERT INTO sqlite_sequence (name, seq)
SELECT 'plan_proposals_new', MAX(seq) FROM (
    SELECT seq FROM sqlite_sequence WHERE name = 'plan_proposals'
    UNION ALL
    SELECT MAX(id) FROM plan_proposals_new
)
HAVING MAX(seq) IS NOT NULL;

DROP TABLE plan_proposals;

ALTER TABLE plan_proposals_new RENAME TO plan_proposals;

CREATE UNIQUE INDEX one_pending_proposal
ON plan_proposals ((1))
WHERE status = 'pending';

UPDATE sessions SET started_at = NULL
WHERE status = 'planned' AND completion_json = '[]';
