"""Connection handling and data access for Amue KeyFlow."""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.constants import BACKUP_DIR, CONFIG_SCHEMA_VERSION, DB_PATH, DEFAULT_SETTINGS
from app.database import migrations
from app.database.models import (
    ActivityEntry,
    AppRule,
    Mapping,
    Profile,
    new_id,
    normalize_executable,
    utc_now,
)

log = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:  # pragma: no cover - safety net
    return str(value)


class Database:
    """Thread safe SQLite wrapper.

    The keyboard engine logs activity from its own thread, so the connection is
    opened with ``check_same_thread=False`` and every access is serialised by an
    ``RLock``.  Writes are short, which keeps the UI responsive.
    """

    def __init__(self, path: Path | str | None = None, backup_dir: Path | str | None = None) -> None:
        self.path = Path(path or DB_PATH)
        self.backup_dir = Path(backup_dir or BACKUP_DIR)
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._connection is not None:
                return self._connection
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fresh = not self.path.exists()
            connection = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            self._connection = connection
            if not fresh:
                self._backup_before_migration(connection)
            migrations.migrate(connection)
            self._ensure_default_profile()
            self._ensure_settings()
            return connection

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.commit()
                self._connection.close()
                self._connection = None

    @property
    def conn(self) -> sqlite3.Connection:
        return self.connect()

    def _backup_before_migration(self, connection: sqlite3.Connection) -> None:
        try:
            version = migrations.current_version(connection)
        except sqlite3.DatabaseError:
            version = 0
        if version >= CONFIG_SCHEMA_VERSION:
            return
        try:
            self.backup_database(f"pre-migration-v{version}")
        except Exception:  # pragma: no cover - backup must never block startup
            log.exception("Could not create a pre-migration backup")

    def backup_database(self, label: str = "manual") -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.backup_dir / f"keyflow-{stamp}-{label}.db"
        with self._lock:
            if self._connection is not None:
                self._connection.commit()
        if self.path.exists():
            shutil.copy2(self.path, target)
        self.prune_backups()
        return target

    def prune_backups(self, keep: int = 20) -> None:
        if not self.backup_dir.exists():
            return
        files = sorted(self.backup_dir.glob("keyflow-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in files[keep:]:
            try:
                stale.unlink()
            except OSError:
                pass

    # -- bootstrap ---------------------------------------------------------
    def _ensure_default_profile(self) -> None:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()
        if row["n"] == 0:
            now = utc_now()
            self.conn.execute(
                "INSERT INTO profiles (id, name, description, created_at, updated_at, is_active)"
                " VALUES (?, ?, ?, ?, ?, 1)",
                (new_id(), "Default", "Your starting profile", now, now),
            )
            self.conn.commit()

    def _ensure_settings(self) -> None:
        existing = {r["key"] for r in self.conn.execute("SELECT key FROM settings")}
        missing = [(k, json.dumps(v)) for k, v in DEFAULT_SETTINGS.items() if k not in existing]
        if missing:
            self.conn.executemany("INSERT INTO settings (key, value) VALUES (?, ?)", missing)
            self.conn.commit()

    # -- settings ----------------------------------------------------------
    def all_settings(self) -> dict[str, Any]:
        with self._lock:
            rows = self.conn.execute("SELECT key, value FROM settings").fetchall()
        result: dict[str, Any] = dict(DEFAULT_SETTINGS)
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                result[row["key"]] = row["value"]
        return result

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, default=_json_default)),
            )
            self.conn.commit()

    def reset_settings(self) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM settings")
            self.conn.commit()
            self._ensure_settings()

    # -- profiles ----------------------------------------------------------
    def list_profiles(self) -> list[Profile]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT p.*, (SELECT COUNT(*) FROM mappings m WHERE m.profile_id = p.id) AS mapping_count"
                " FROM profiles p ORDER BY p.created_at ASC"
            ).fetchall()
        return [Profile.from_row(r) for r in rows]

    def get_profile(self, profile_id: str) -> Profile | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        return Profile.from_row(row) if row else None

    def get_profile_by_name(self, name: str) -> Profile | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM profiles WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        return Profile.from_row(row) if row else None

    def create_profile(self, name: str, description: str = "") -> Profile:
        name = name.strip()
        if not name:
            raise ValueError("Profile name cannot be empty.")
        if self.get_profile_by_name(name):
            raise ValueError(f"A profile named “{name}” already exists.")
        profile = Profile(id=new_id(), name=name, description=description.strip(), mapping_count=0)
        with self._lock:
            self.conn.execute(
                "INSERT INTO profiles (id, name, description, created_at, updated_at, is_active)"
                " VALUES (?, ?, ?, ?, ?, 0)",
                (profile.id, profile.name, profile.description, profile.created_at, profile.updated_at),
            )
            self.conn.commit()
        return profile

    def update_profile(self, profile: Profile) -> None:
        name = profile.name.strip()
        if not name:
            raise ValueError("Profile name cannot be empty.")
        clash = self.get_profile_by_name(name)
        if clash and clash.id != profile.id:
            raise ValueError(f"A profile named “{name}” already exists.")
        profile.updated_at = utc_now()
        with self._lock:
            self.conn.execute(
                "UPDATE profiles SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                (name, profile.description, profile.updated_at, profile.id),
            )
            self.conn.commit()

    def delete_profile(self, profile_id: str) -> None:
        with self._lock:
            total = self.conn.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()["n"]
            if total <= 1:
                raise ValueError("At least one profile must exist.")
            active = self.conn.execute("SELECT is_active FROM profiles WHERE id = ?", (profile_id,)).fetchone()
            self.conn.execute("DELETE FROM mappings WHERE profile_id = ?", (profile_id,))
            self.conn.execute("DELETE FROM app_rules WHERE profile_id = ?", (profile_id,))
            self.conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
            if active and active["is_active"]:
                fallback = self.conn.execute("SELECT id FROM profiles LIMIT 1").fetchone()
                if fallback:
                    self.conn.execute("UPDATE profiles SET is_active = 1 WHERE id = ?", (fallback["id"],))
            self.conn.commit()

    def set_active_profile(self, profile_id: str) -> None:
        with self._lock:
            self.conn.execute("UPDATE profiles SET is_active = 0")
            self.conn.execute("UPDATE profiles SET is_active = 1 WHERE id = ?", (profile_id,))
            self.conn.commit()

    def active_profile(self) -> Profile | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM profiles WHERE is_active = 1 LIMIT 1").fetchone()
            if row is None:
                row = self.conn.execute("SELECT * FROM profiles LIMIT 1").fetchone()
        return Profile.from_row(row) if row else None

    # -- app rules ---------------------------------------------------------
    def list_app_rules(self, profile_id: str | None = None) -> list[AppRule]:
        with self._lock:
            if profile_id:
                rows = self.conn.execute(
                    "SELECT * FROM app_rules WHERE profile_id = ? ORDER BY executable COLLATE NOCASE",
                    (profile_id,),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM app_rules ORDER BY executable COLLATE NOCASE"
                ).fetchall()
        return [AppRule.from_row(r) for r in rows]

    def add_app_rule(self, profile_id: str, executable: str) -> AppRule:
        name = normalize_executable(executable)
        if self.get_profile(profile_id) is None:
            raise ValueError("Profile not found.")
        rule = AppRule(id=new_id(), profile_id=profile_id, executable=name)
        with self._lock:
            try:
                self.conn.execute(
                    "INSERT INTO app_rules (id, profile_id, executable, created_at) VALUES (?, ?, ?, ?)",
                    (rule.id, rule.profile_id, rule.executable, rule.created_at),
                )
                self.conn.commit()
            except sqlite3.IntegrityError:
                self.conn.rollback()
                owner = self.profile_for_executable(name)
                if owner is not None:
                    raise ValueError(f"“{name}” already switches to “{owner.name}”.") from None
                raise ValueError(f"“{name}” is already assigned to a profile.") from None
        return rule

    def delete_app_rule(self, rule_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM app_rules WHERE id = ?", (rule_id,))
            self.conn.commit()

    def profile_for_executable(self, executable: str) -> Profile | None:
        try:
            name = normalize_executable(executable)
        except ValueError:
            return None
        with self._lock:
            row = self.conn.execute(
                "SELECT p.* FROM profiles p JOIN app_rules r ON r.profile_id = p.id"
                " WHERE r.executable = ? COLLATE NOCASE LIMIT 1",
                (name,),
            ).fetchone()
        return Profile.from_row(row) if row else None

    # -- mappings ----------------------------------------------------------
    def list_mappings(self, profile_id: str | None = None) -> list[Mapping]:
        with self._lock:
            if profile_id:
                rows = self.conn.execute(
                    "SELECT * FROM mappings WHERE profile_id = ? ORDER BY created_at ASC", (profile_id,)
                ).fetchall()
            else:
                rows = self.conn.execute("SELECT * FROM mappings ORDER BY created_at ASC").fetchall()
        return [Mapping.from_row(r) for r in rows]

    def get_mapping(self, mapping_id: str) -> Mapping | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM mappings WHERE id = ?", (mapping_id,)).fetchone()
        return Mapping.from_row(row) if row else None

    def save_mapping(self, mapping: Mapping) -> Mapping:
        mapping.updated_at = utc_now()
        row = mapping.to_row()
        with self._lock:
            exists = self.conn.execute("SELECT 1 FROM mappings WHERE id = ?", (mapping.id,)).fetchone()
            if exists:
                self.conn.execute(
                    "UPDATE mappings SET profile_id=?, name=?, description=?, input_configuration=?,"
                    " output_configuration=?, mapping_type=?, trigger_behavior=?, delay=?, is_enabled=?,"
                    " updated_at=? WHERE id=?",
                    (
                        row["profile_id"], row["name"], row["description"], row["input_configuration"],
                        row["output_configuration"], row["mapping_type"], row["trigger_behavior"],
                        row["delay"], row["is_enabled"], row["updated_at"], row["id"],
                    ),
                )
            else:
                self.conn.execute(
                    "INSERT INTO mappings (id, profile_id, name, description, input_configuration,"
                    " output_configuration, mapping_type, trigger_behavior, delay, is_enabled, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["id"], row["profile_id"], row["name"], row["description"], row["input_configuration"],
                        row["output_configuration"], row["mapping_type"], row["trigger_behavior"], row["delay"],
                        row["is_enabled"], row["created_at"], row["updated_at"],
                    ),
                )
            self.conn.commit()
        return mapping

    def delete_mapping(self, mapping_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM mappings WHERE id = ?", (mapping_id,))
            self.conn.commit()

    def set_mappings_enabled(self, profile_id: str, enabled: bool) -> None:
        with self._lock:
            self.conn.execute("UPDATE mappings SET is_enabled = ? WHERE profile_id = ?", (1 if enabled else 0, profile_id))
            self.conn.commit()

    def recent_mappings(self, limit: int = 6) -> list[Mapping]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM mappings ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Mapping.from_row(r) for r in rows]

    def count_mappings(self) -> tuple[int, int]:
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(is_enabled), 0) AS active FROM mappings"
            ).fetchone()
        return int(row["total"]), int(row["active"])

    # -- activity ----------------------------------------------------------
    def add_activity(
        self,
        mapping: Mapping | None,
        input_text: str,
        output_text: str,
        status: str = "success",
        detail: str = "",
    ) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO activity (mapping_id, mapping_name, input_text, output_text, profile_id,"
                " timestamp, status, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    mapping.id if mapping else "",
                    mapping.name if mapping else "",
                    input_text,
                    output_text,
                    mapping.profile_id if mapping else "",
                    utc_now(),
                    status,
                    detail,
                ),
            )
            self.conn.commit()

    def list_activity(self, limit: int = 200, search: str = "") -> list[ActivityEntry]:
        query = "SELECT * FROM activity"
        params: list[Any] = []
        if search:
            query += " WHERE mapping_name LIKE ? OR input_text LIKE ? OR output_text LIKE ?"
            like = f"%{search}%"
            params.extend([like, like, like])
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [ActivityEntry.from_row(r) for r in rows]

    def clear_activity(self) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM activity")
            self.conn.commit()

    def prune_activity(self, keep: int) -> None:
        with self._lock:
            self.conn.execute(
                "DELETE FROM activity WHERE id NOT IN (SELECT id FROM activity ORDER BY id DESC LIMIT ?)",
                (max(0, keep),),
            )
            self.conn.commit()

    # -- bulk --------------------------------------------------------------
    def replace_all(
        self,
        profiles: Iterable[Profile],
        mappings: Iterable[Mapping],
        active_id: str,
        app_rules: Iterable[AppRule] = (),
    ) -> None:
        """Atomically replace every profile, mapping and app rule (used by import)."""
        with self._lock:
            connection = self.conn
            try:
                connection.execute("BEGIN")
                connection.execute("DELETE FROM app_rules")
                connection.execute("DELETE FROM mappings")
                connection.execute("DELETE FROM profiles")
                for profile in profiles:
                    connection.execute(
                        "INSERT INTO profiles (id, name, description, created_at, updated_at, is_active)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            profile.id, profile.name, profile.description, profile.created_at,
                            profile.updated_at, 1 if profile.id == active_id else 0,
                        ),
                    )
                for rule in app_rules:
                    connection.execute(
                        "INSERT INTO app_rules (id, profile_id, executable, created_at) VALUES (?, ?, ?, ?)",
                        (rule.id, rule.profile_id, rule.executable, rule.created_at),
                    )
                for mapping in mappings:
                    row = mapping.to_row()
                    connection.execute(
                        "INSERT INTO mappings (id, profile_id, name, description, input_configuration,"
                        " output_configuration, mapping_type, trigger_behavior, delay, is_enabled, created_at, updated_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            row["id"], row["profile_id"], row["name"], row["description"],
                            row["input_configuration"], row["output_configuration"], row["mapping_type"],
                            row["trigger_behavior"], row["delay"], row["is_enabled"], row["created_at"],
                            row["updated_at"],
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
