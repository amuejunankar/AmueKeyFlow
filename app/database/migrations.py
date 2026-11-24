"""SQLite schema migrations.

``PRAGMA user_version`` tracks the applied schema version.  Each migration runs
inside a single transaction, so a failure leaves the database untouched.
"""

from __future__ import annotations

import logging
import sqlite3

log = logging.getLogger(__name__)

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS profiles (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mappings (
    id                   TEXT PRIMARY KEY,
    profile_id           TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name                 TEXT NOT NULL DEFAULT '',
    description          TEXT NOT NULL DEFAULT '',
    input_configuration  TEXT NOT NULL,
    output_configuration TEXT NOT NULL,
    mapping_type         TEXT NOT NULL,
    trigger_behavior     TEXT NOT NULL DEFAULT 'press',
    delay                INTEGER NOT NULL DEFAULT 0,
    is_enabled           INTEGER NOT NULL DEFAULT 1,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mappings_profile ON mappings(profile_id);
CREATE INDEX IF NOT EXISTS idx_mappings_updated ON mappings(updated_at DESC);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    mapping_id TEXT,
    mapping_name TEXT NOT NULL DEFAULT '',
    input_text TEXT NOT NULL DEFAULT '',
    output_text TEXT NOT NULL DEFAULT '',
    profile_id TEXT,
    timestamp  TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'success',
    detail     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(timestamp DESC);
"""

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS app_rules (
    id         TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    executable TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_app_rules_profile ON app_rules(profile_id);
"""

MIGRATIONS: dict[int, str] = {
    1: SCHEMA_V1,
    2: SCHEMA_V2,
}


def current_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def migrate(connection: sqlite3.Connection) -> int:
    """Apply every pending migration; returns the resulting schema version."""
    version = current_version(connection)
    for target in sorted(MIGRATIONS):
        if target <= version:
            continue
        script = MIGRATIONS[target]
        log.info("Applying database migration %s", target)
        try:
            connection.execute("BEGIN")
            for statement in _split_statements(script):
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {int(target)}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        version = target
    return version


def _split_statements(script: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(buffer))
            buffer = []
    if buffer:
        statements.append("\n".join(buffer))
    return statements
