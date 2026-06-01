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
    created_at TEXT NOT NULL,
    updated_at TEXT
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
