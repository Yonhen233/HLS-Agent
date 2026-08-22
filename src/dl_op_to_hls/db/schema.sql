CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE NOT NULL,
    task_type TEXT NOT NULL,
    name TEXT NOT NULL,
    objective TEXT,
    selected_path TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS operators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op_type TEXT NOT NULL,
    name TEXT NOT NULL,
    input_shape TEXT,
    output_shape TEXT,
    dtype TEXT,
    params_json TEXT,
    spec_hash TEXT UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS implementations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    operator_id INTEGER,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    hls_project_dir TEXT,
    hls_file_path TEXT,
    testbench_path TEXT,
    tcl_path TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(operator_id) REFERENCES operators(id)
);

CREATE TABLE IF NOT EXISTS synthesis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    implementation_id INTEGER,
    tool TEXT,
    tool_version TEXT,
    part TEXT,
    clock_period REAL,
    latency_min INTEGER,
    latency_max INTEGER,
    ii_min INTEGER,
    ii_max INTEGER,
    dsp INTEGER,
    bram INTEGER,
    lut INTEGER,
    ff INTEGER,
    timing_met INTEGER,
    report_path TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(implementation_id) REFERENCES implementations(id)
);

CREATE TABLE IF NOT EXISTS failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    implementation_id INTEGER,
    error_type TEXT,
    error_message TEXT,
    log_summary TEXT,
    suggested_fix TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(implementation_id) REFERENCES implementations(id)
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    server TEXT,
    status TEXT NOT NULL,
    input_hash TEXT,
    output_hash TEXT,
    duration_ms INTEGER,
    error_type TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts
USING fts5(chunk_text, source_id, metadata_json);

CREATE TABLE IF NOT EXISTS rag_embeddings (
    chunk_id INTEGER NOT NULL,
    model_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    embedding_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (chunk_id, model_id),
    FOREIGN KEY (chunk_id) REFERENCES rag_chunks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rag_embeddings_model
ON rag_embeddings(model_id, chunk_id);

CREATE TABLE IF NOT EXISTS memory_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_type TEXT NOT NULL,
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source_run_id TEXT,
    importance INTEGER DEFAULT 1,
    confidence REAL DEFAULT 1.0,
    status TEXT DEFAULT 'active',
    namespace TEXT DEFAULT 'global',
    user_id TEXT,
    project_id TEXT,
    session_id TEXT,
    expires_at TEXT,
    supersedes_id INTEGER,
    content_hash TEXT,
    access_count INTEGER DEFAULT 0,
    last_accessed_at TEXT,
    feedback_score REAL DEFAULT 0.0,
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    FOREIGN KEY (supersedes_id) REFERENCES memory_items(id)
);

CREATE TABLE IF NOT EXISTS memory_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL,
    user_id TEXT,
    score REAL NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memory_items(id)
);

CREATE TABLE IF NOT EXISTS memory_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact TEXT NOT NULL,
    source_run_id TEXT,
    source_artifact TEXT,
    confidence REAL DEFAULT 1.0,
    tags_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS procedural_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    trigger_conditions_json TEXT,
    success_criteria_json TEXT,
    source_run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_jobs (
    job_id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER DEFAULT 100,
    available_at REAL NOT NULL,
    lease_owner TEXT,
    lease_expires_at REAL,
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    state_version INTEGER DEFAULT 0,
    result_json TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_jobs_claim
ON agent_jobs(status, available_at, priority, created_at);

CREATE TABLE IF NOT EXISTS agent_state_commits (
    commit_key TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    payload_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES agent_jobs(job_id)
);

CREATE TABLE IF NOT EXISTS agent_outbox (
    event_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT,
    FOREIGN KEY(job_id) REFERENCES agent_jobs(job_id)
);

CREATE TABLE IF NOT EXISTS agent_releases (
    component_type TEXT NOT NULL,
    component_name TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'registered',
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(component_type, component_name, version)
);

CREATE TABLE IF NOT EXISTS release_routes (
    component_type TEXT NOT NULL,
    component_name TEXT NOT NULL,
    baseline_version TEXT NOT NULL,
    candidate_version TEXT,
    canary_percent REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'stable',
    updated_at TEXT NOT NULL,
    PRIMARY KEY(component_type, component_name)
);

CREATE TABLE IF NOT EXISTS release_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component_type TEXT NOT NULL,
    component_name TEXT NOT NULL,
    baseline_version TEXT NOT NULL,
    candidate_version TEXT NOT NULL,
    baseline_metrics_json TEXT NOT NULL,
    candidate_metrics_json TEXT NOT NULL,
    decision TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_feedback_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL,
    user_id TEXT,
    score REAL NOT NULL,
    reason TEXT,
    evidence_json TEXT NOT NULL,
    status TEXT NOT NULL,
    risk_flags_json TEXT NOT NULL,
    reviewer TEXT,
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    applied_feedback_id INTEGER,
    FOREIGN KEY(memory_id) REFERENCES memory_items(id)
);

CREATE INDEX IF NOT EXISTS idx_memory_feedback_candidates_status
ON memory_feedback_candidates(status, created_at);

CREATE TABLE IF NOT EXISTS short_lived_credentials (
    token_hash TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    audience TEXT NOT NULL,
    scopes_json TEXT NOT NULL,
    expires_at REAL NOT NULL,
    max_uses INTEGER NOT NULL DEFAULT 1,
    uses INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id TEXT PRIMARY KEY,
    run_id TEXT,
    run_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 1,
    active_checkpoint_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    next_message_seq INTEGER NOT NULL DEFAULT 1,
    next_event_seq INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    compaction_history_json TEXT NOT NULL DEFAULT '[]',
    interrupt_reason TEXT,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_updated
ON agent_sessions(updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_session_messages (
    session_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    retracted INTEGER NOT NULL DEFAULT 0,
    retracted_at TEXT,
    retracted_by_message_id TEXT,
    PRIMARY KEY(session_id, message_id),
    UNIQUE(session_id, sequence),
    FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_session_messages_order
ON agent_session_messages(session_id, sequence);

CREATE TABLE IF NOT EXISTS agent_session_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(session_id, sequence),
    FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_session_events_order
ON agent_session_events(session_id, sequence);

CREATE TABLE IF NOT EXISTS agent_session_checkpoints (
    checkpoint_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    parent_checkpoint_id TEXT,
    run_id TEXT,
    generation INTEGER NOT NULL,
    reason TEXT NOT NULL,
    state_json TEXT NOT NULL,
    runtime_json TEXT NOT NULL DEFAULT '{}',
    state_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(session_id, checkpoint_id),
    UNIQUE(session_id, sequence),
    FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY(session_id, parent_checkpoint_id)
        REFERENCES agent_session_checkpoints(session_id, checkpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_session_checkpoints_order
ON agent_session_checkpoints(session_id, sequence);

CREATE TABLE IF NOT EXISTS agent_session_approvals (
    approval_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args_hash TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    max_uses INTEGER NOT NULL DEFAULT 1,
    use_count INTEGER NOT NULL DEFAULT 0,
    feedback TEXT,
    decided_at TEXT,
    last_used_at TEXT,
    FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_session_approvals_lookup
ON agent_session_approvals(session_id, tool_name, args_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_delegation_messages (
    message_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    session_id TEXT,
    sequence INTEGER NOT NULL,
    message_type TEXT NOT NULL,
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    parent_message_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_agent_delegation_messages_correlation
ON agent_delegation_messages(run_id, correlation_id, sequence);
