"""
Database layer for Phase 2 flood forecasting.
Uses SQLite for portability (no server required).
"""
import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent / "flood_forecast.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    lat             REAL NOT NULL,
    lon             REAL NOT NULL,
    type            TEXT DEFAULT 'outlet',
    area_km2        REAL DEFAULT 0,
    slope_s0        REAL DEFAULT 0.01,
    w_channel       REAL DEFAULT 10,
    cn_prior        REAL DEFAULT 75,
    n_prior         REAL DEFAULT 0.04,
    tc_hours        REAL DEFAULT 1.0,
    cn_corrected    REAL,
    n_corrected     REAL,
    alert_l1_m      REAL DEFAULT 1.0,
    alert_l2_m      REAL DEFAULT 1.5,
    alert_l3_m      REAL DEFAULT 2.0,
    max_elev        REAL DEFAULT 0,
    min_elev        REAL DEFAULT 0,
    delta_h         REAL DEFAULT 0,
    catchment_geojson TEXT,
    dem_source      TEXT,
    training_status TEXT DEFAULT 'untrained',
    training_meta   TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subpoints (
    id          TEXT PRIMARY KEY,
    station_id  TEXT NOT NULL,
    name        TEXT NOT NULL,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    type        TEXT DEFAULT 'rain_gauge',  -- 'rain_gauge' | 'upstream_level'
    note        TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id      TEXT NOT NULL,
    timestamp       DATETIME NOT NULL,
    rainfall_mm     REAL DEFAULT 0,
    water_level_m   REAL,
    flow_m3s        REAL,
    h_up_m          REAL DEFAULT 0,
    api_mm          REAL DEFAULT 0,
    quality         INTEGER DEFAULT 1,
    source          TEXT DEFAULT 'csv',
    UNIQUE(station_id, timestamp)
);

CREATE TABLE IF NOT EXISTS forecasts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id      TEXT NOT NULL,
    issue_time      DATETIME NOT NULL,
    lead_minutes    INTEGER NOT NULL,   -- 5,10,...,60
    h_physics       REAL,
    h_pinn          REAL,
    h_final         REAL,
    q_final         REAL,
    cn_corrected    REAL,
    n_corrected     REAL,
    alert_level     INTEGER DEFAULT 0,
    model_version   TEXT DEFAULT 'physics'
);

CREATE INDEX IF NOT EXISTS idx_obs_station_time
    ON observations(station_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_fc_station_issue
    ON forecasts(station_id, issue_time);
"""

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

# Columns added after initial schema — safe to ADD if missing
_MIGRATIONS = [
    "ALTER TABLE stations ADD COLUMN max_elev REAL DEFAULT 0",
    "ALTER TABLE stations ADD COLUMN min_elev REAL DEFAULT 0",
    "ALTER TABLE stations ADD COLUMN delta_h REAL DEFAULT 0",
    "ALTER TABLE stations ADD COLUMN dem_source TEXT DEFAULT ''",
    "ALTER TABLE stations ADD COLUMN cn_corrected REAL",
    "ALTER TABLE stations ADD COLUMN n_corrected REAL",
    "ALTER TABLE stations ADD COLUMN training_status TEXT DEFAULT 'untrained'",
    "ALTER TABLE stations ADD COLUMN training_meta TEXT",
    "ALTER TABLE stations ADD COLUMN catchment_geojson TEXT",
    "ALTER TABLE stations ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    "ALTER TABLE stations ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    "ALTER TABLE observations ADD COLUMN h_up_m REAL DEFAULT 0",
    "ALTER TABLE observations ADD COLUMN api_mm REAL DEFAULT 0",
]

def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Run migrations: ignore errors for columns that already exist
        for stmt in _MIGRATIONS:
            try:
                conn.execute(stmt)
            except Exception:
                pass  # column already exists — skip
    return str(DB_PATH)

if __name__ == "__main__":
    p = init_db()
    print(f"Database initialized at: {p}")
