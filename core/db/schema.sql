CREATE TABLE IF NOT EXISTS jobs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type       TEXT NOT NULL,                   -- 'recon' | 'xss' | 'sqli' | 'ffuf' | 'report'
    target         TEXT NOT NULL,
    params_json    TEXT NOT NULL DEFAULT '{}',
    status         TEXT NOT NULL DEFAULT 'queued',   -- queued|running|done|failed|cancelled
    created_by     TEXT NOT NULL,                    -- discord user id
    channel_id     TEXT NOT NULL,
    message_id     TEXT,                             -- discord message being edited for progress
    created_at     TEXT NOT NULL,
    started_at     TEXT,
    finished_at    TEXT,
    raw_output_dir TEXT,
    error          TEXT
);

CREATE TABLE IF NOT EXISTS findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER REFERENCES jobs(id),
    target        TEXT NOT NULL,
    tool          TEXT NOT NULL,
    finding_type  TEXT NOT NULL,                     -- subdomain|live-host|exposure|endpoint|vuln
    severity      TEXT,                              -- info|low|medium|high|critical
    title         TEXT NOT NULL,
    detail        TEXT,
    url           TEXT,
    hash          TEXT NOT NULL UNIQUE,               -- sha256(tool|target|type|normalized-detail)
    status        TEXT NOT NULL DEFAULT 'new',        -- new|needs-review|reviewed-priority|reviewed-low|reported|false-positive|ignored
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_target ON findings(target);
CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status);
CREATE INDEX IF NOT EXISTS idx_findings_job ON findings(job_id);

CREATE TABLE IF NOT EXISTS claude_invocations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp      TEXT NOT NULL,
    purpose        TEXT NOT NULL,                    -- triage|report
    job_id         INTEGER,
    backend        TEXT NOT NULL,                    -- cli|api
    model          TEXT,
    duration_ms    INTEGER,
    total_cost_usd REAL,
    success        INTEGER NOT NULL,
    error          TEXT
);
CREATE INDEX IF NOT EXISTS idx_claude_invocations_ts ON claude_invocations(timestamp);

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL,
    actor        TEXT NOT NULL,                      -- discord user id or 'system'
    action       TEXT NOT NULL,                      -- command:/recon, scope:reject, job:start, job:cancel...
    target       TEXT,
    tool         TEXT,
    job_id       INTEGER,
    details_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(timestamp);

CREATE TABLE IF NOT EXISTS report_drafts (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_ids_json          TEXT NOT NULL,           -- JSON array of findings.id this draft covers
    target                    TEXT NOT NULL,
    platform                  TEXT NOT NULL,           -- 'hackerone' (only one with real submission today)
    program_handle            TEXT NOT NULL,
    title                     TEXT NOT NULL,
    impact                    TEXT NOT NULL,
    vulnerability_information TEXT NOT NULL,
    severity_rating           TEXT,
    status                    TEXT NOT NULL DEFAULT 'pending', -- pending|submitted|discarded
    created_by                TEXT NOT NULL,
    created_at                TEXT NOT NULL,
    submitted_at              TEXT,
    external_report_id        TEXT,
    external_report_url       TEXT
);
CREATE INDEX IF NOT EXISTS idx_report_drafts_status ON report_drafts(status);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO settings (key, value) VALUES ('paused', '0');
INSERT OR IGNORE INTO settings (key, value) VALUES ('claude_daily_budget', '20');
