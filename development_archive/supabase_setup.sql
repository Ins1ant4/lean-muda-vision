-- Run this in Supabase Dashboard > SQL Editor.
-- Idempotent: safe to re-run after schema changes.

-- ===== mudas_log: classified downtime events =====
CREATE TABLE IF NOT EXISTS mudas_log (
    id            BIGSERIAL PRIMARY KEY,
    timestamp     TIMESTAMPTZ DEFAULT NOW(),
    machine_id    TEXT DEFAULT 'RH1',
    stop_duration REAL,
    classification TEXT,
    state         TEXT
);
ALTER TABLE mudas_log DISABLE ROW LEVEL SECURITY;
ALTER TABLE mudas_log ADD COLUMN IF NOT EXISTS machine_id TEXT DEFAULT 'RH1';

-- ===== production_log: every OK / Scrap piece =====
CREATE TABLE IF NOT EXISTS production_log (
    id            BIGSERIAL PRIMARY KEY,
    timestamp     TIMESTAMPTZ DEFAULT NOW(),
    machine_id    TEXT NOT NULL DEFAULT 'RH1',
    piece_number  INT,
    result        TEXT NOT NULL,             -- 'OK' or 'Scrap'
    sewing_time_s REAL,
    rework_count  INT
);
ALTER TABLE production_log DISABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_prod_machine_time ON production_log (machine_id, timestamp DESC);

-- ===== machine_status: live state, single row per machine =====
CREATE TABLE IF NOT EXISTS machine_status (
    machine_id          TEXT PRIMARY KEY,
    state               TEXT,
    is_moving           BOOLEAN,
    current_downtime_s  REAL,
    last_classification TEXT,
    last_heartbeat      TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE machine_status DISABLE ROW LEVEL SECURITY;
