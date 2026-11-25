"""Application bootstrap and the controller that wires every service together."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication, QFileDialog

from app.audio.voice_engine import VoiceEngine
from app.constants import (
    APP_NAME,
    APP_SLUG,
    APP_VERSION,
    DATA_DIR,
    DEFAULT_SETTINGS,
    EXPORT_DIR,
    LOG_DIR,
    LOG_FORMAT,
)
from app.database.database import Database
from app.database.models import AppOverride, Mapping
from app.engine.conflict_detector import conflicts_by_mapping
from app.engine.engine import MappingEngine
from app.engine.safety_manager import SafetyManager
from app.services.activity_logger import ActivityLogger
from app.services.import_export import (
    ImportValidationError,
    import_payload,
    load_payload,
    parse_overrides,
    parse_payload,
    write_export,
)
from app.services.foreground_watcher import ForegroundWatcher
from app.services.power_manager import PowerManager
from app.services.profile_manager import ProfileManager
from app.services.settings_manager import SettingsManager
from app.services.startup_manager import StartupManager
from app.services.tray_manager import TrayManager
from app.ui import theme
from app.ui.components.dialogs import ConfirmDialog, SearchDialog, Toast
from app.ui.components.import_dialog import ImportDialog, MessageSheet
from app.ui.icons import clear_cache as clear_icon_cache
from app.ui.mapping_editor import MappingEditor
from app.ui.profiles import AppOverrideDialog, AppRulesDialog, ProfileDialog

log = logging.getLogger(__name__)


def configure_logging(level: str = "INFO", debug: bool = False) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else getattr(logging, str(level).upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)
    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "keyflow.log", maxBytes=1_500_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)


class EngineBridge(QObject):
    """Marshals engine callbacks from the hook thread onto the UI thread."""

    event = Signal(str, object)


class AppController(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.window = None
        self.tray: TrayManager | None = None
        self._conflict_cache: set[str] = set()
        self._refreshing = False
        self._shutting_down = False
        self._tray_hint_shown = False
        self._active_override: AppOverride | None = None
        self._engine_scope: tuple[str, str] = ("", "")

        for folder in (DATA_DIR, LOG_DIR, EXPORT_DIR):
            folder.mkdir(parents=True, exist_ok=True)

        configure_logging(
            str(DEFAULT_SETTINGS["logging_level"]),
            bool(DEFAULT_SETTINGS["debug_mode"]),
        )
        log.info("Starting %s %s", APP_NAME, APP_VERSION)

        self.db = Database()
        self.db.connect()
        self.settings = SettingsManager(self.db)
        self.voice = VoiceEngine(self.settings)
        self.profiles = ProfileManager(self.db, self.settings)
        self.activity = ActivityLogger(self.db, self.settings)
        self.power = PowerManager()

        self.bridge = EngineBridge()
        self.bridge.event.connect(self._on_engine_event, Qt.QueuedConnection)
        self.engine = MappingEngine(self.settings, self.activity, notify=self._engine_notify)
        self.safety = SafetyManager(self.engine, self.settings)
        self.startup = StartupManager()
        self.foreground = ForegroundWatcher(parent=self)
        self.foreground.changed.connect(self._on_foreground_app, Qt.QueuedConnection)

        self.settings.add_listener(self._on_setting_changed)
        self.profiles.add_listener(self._on_profiles_changed)

        configure_logging(
            str(self.settings.get("logging_level", "INFO")),
            self.settings.get_bool("debug_mode", False),
        )

        # Caffeine is a Windows execution-state flag owned by this thread, so it is
        # restored once at startup and dropped again on exit.
        if self.settings.get_bool("caffeine_enabled", False):
            ok, message = self.power.set_enabled(True)
            if not ok:
                log.warning("Caffeine did not restore: %s", message)
                self.settings.set("caffeine_enabled", False)

        # If the installer (or the user) added a startup entry, adopt it as the
        # effective setting instead of silently deleting it on first launch.
        if (
            StartupManager.is_supported()
            and not self.settings.get_bool("start_with_windows", False)
            and self.startup.is_enabled()
        ):
            log.info("Adopting the existing startup entry")
            self.settings.set("start_with_windows", True)

        # Keep the registry entry in sync without ever duplicating it.
        if StartupManager.is_supported():
            ok, message = self.startup.sync(self.settings.get_bool("start_with_windows", False))
            if not ok:
                log.warning("Startup registry sync failed: %s", message)

        self.apply_appearance()
        self._conflict_cache = set(
            conflicts_by_mapping(self.profiles.active_mappings())
        )
        self._sync_engine_scope(force=True)
        self.engine.configure()

    # -- attachments -------------------------------------------------------
    def attach_window(self, window) -> None:
        self.window = window

    def attach_tray(self, tray: TrayManager) -> None:
        self.tray = tray

    # -- startup -----------------------------------------------------------
    def start_engine(self) -> bool:
        if not self.settings.get_bool("engine_enabled", True):
            log.info("Keyboard engine disabled in settings")
            return False
        ok = self.engine.start()
        if not ok:
            self.notify(
                "The keyboard engine could not start. Another keyboard tool may be blocking the hook — "
                "check the log and try Settings → Resume engine.",
                "error",
            )
        return ok

    def start_voice(self) -> None:
        """Resume Voice FX when it was left running the last time."""
        if not self.settings.get_bool("voice_fx_enabled", False):
            return
        ok, message = self.voice.start()
        if not ok:
            log.warning("Voice FX did not resume: %s", message)

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        log.info("Shutting down")
        try:
            self.foreground.stop()
        except Exception:
            log.exception("Foreground watcher stop failed")
        try:
            self.voice.stop()
        except Exception:
            log.exception("Voice FX stop failed")
        try:
            self.power.release()
        except Exception:
            log.exception("Caffeine release failed")
        try:
            self.safety.shutdown()
        except Exception:
            log.exception("Engine shutdown failed")
        try:
            self.db.backup_database("exit")
        except Exception:
            log.exception("Exit backup failed")
        try:
            self.db.close()
        except Exception:
            log.exception("Database close failed")
        if self.tray:
            self.tray.hide()

    # -- notification helpers ---------------------------------------------
    def _engine_notify(self, event: str, payload: dict) -> None:
        self.bridge.event.emit(event, payload)

    def notify(self, text: str, tone: str = "success") -> None:
        if self.window is not None:
            Toast.show_message(self.window, text, tone)
        else:
            log.info("%s", text)

    def open_search(self) -> None:
        if self.window is None:
            return
        dialog = SearchDialog(self, self.window)
        dialog.center_on_parent()
        if dialog.exec() == dialog.Accepted and dialog.selected_id:
            self.edit_mapping(dialog.selected_id)

    # -- appearance --------------------------------------------------------
    def _system_is_dark(self) -> bool:
        try:
            hints = QGuiApplication.styleHints()
            scheme = hints.colorScheme()
            return scheme == Qt.ColorScheme.Dark
        except Exception:  # pragma: no cover - older Qt
            return True

    def apply_appearance(self) -> None:
        theme_name = str(self.settings.get("theme", "dark"))
        accent = str(self.settings.get("accent", "violet"))
        theme.apply_appearance(theme_name, accent, self._system_is_dark())
        clear_icon_cache()
        self.app.setStyleSheet(theme.stylesheet())
        if self.window is not None:
            self.window.refresh_all_pages()
            self.window.update()
        if self.tray is not None:
            self.tray.refresh_state()

    # -- state -------------------------------------------------------------
    def conflict_ids(self) -> set[str]:
        return self._conflict_cache

    def _sync_widgets(self) -> None:
        if self.window is None:
            return
        status = self.engine.status()
        self.window.sidebar.set_status(status["running"], status["enabled"], status["paused"], status["emergency"])
        self.window.topbar.set_mappings_enabled(status["enabled"])
        self.window.topbar.set_paused(status["paused"])
        if self.tray is not None:
            self.tray.refresh_state()

    def refresh_state(self, full: bool = False) -> None:
        if self._refreshing or self._shutting_down:
            return
        self._refreshing = True
        try:
            self._conflict_cache = set(conflicts_by_mapping(self.profiles.active_mappings()))
            self._sync_engine_scope(force=True)
            self.engine.configure()
            if self.window is not None:
                if full:
                    self.window.refresh_all_pages()
                else:
                    self.window.refresh_current_page()
            if self.tray is not None:
                self.tray.refresh_state()
        finally:
            self._refreshing = False

    def _on_profiles_changed(self) -> None:
        QTimer.singleShot(0, lambda: self.refresh_state(full=True))

    def _on_setting_changed(self, key: str, value) -> None:  # noqa: C901
        try:
            if key in {"theme", "accent"}:
                self.apply_appearance()
                return
            if key == "start_with_windows":
                ok, message = self.startup.sync(bool(value))
                if not ok:
                    log.warning("Startup sync failed: %s", message)
            elif key == "engine_enabled":
                if value and not self.engine.running:
                    self.start_engine()
                elif not value and self.engine.running:
                    self.engine.stop()
            elif key in {"key_repeat_policy", "repeat_throttle_ms", "emergency_hotkey_enabled"}:
                self.engine.configure()
            elif key == "mappings_enabled":
                self.engine.set_mappings_enabled(bool(value))
            elif key == "logging_level":
                configure_logging(str(value), self.settings.get_bool("debug_mode", False))
            elif key == "debug_mode":
                configure_logging(str(self.settings.get("logging_level", "INFO")), bool(value))
            elif key == "activity_max_entries":
                self.db.prune_activity(int(value))
            elif key == "auto_switch_profiles" and value:
                self._on_foreground_app(self.foreground.last_external)
            self._sync_widgets()
        except Exception:
            log.exception("Handling setting %s failed", key)

    def _on_engine_event(self, event: str, payload: dict) -> None:
        if self._shutting_down:
            return
        log.debug("Engine event: %s %s", event, payload)
        if event == "mapping_triggered":
            if self.window is not None and self.window.current_page_key == "activity":
                self.window.pages["activity"].refresh()
            return
        if event == "mapping_failed":
            self.notify(f"Mapping “{payload.get('name', '')}” failed: {payload.get('error', 'unknown error')}", "error")
        elif event == "engine_failed":
            self.notify(payload.get("error", "The keyboard engine stopped."), "error")
            self._sync_widgets()
        elif event == "emergency_stop":
            self.notify(f"Emergency stop: {payload.get('reason', 'mappings disabled')}. Your keyboard is normal.", "warning")
            self._sync_widgets()
            if self.window is not None:
                self.show_window()
                self.window.refresh_current_page()
        else:
            self._sync_widgets()

    # -- window / tray -----------------------------------------------------
    def show_window(self) -> None:
        if self.window is None:
            return
        if self.window.isMinimized():
            self.window.showNormal()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.window.refresh_current_page()

    def navigate(self, key: str) -> None:
        self.show_window()
        if self.window is not None:
            self.window.navigate(key)

    def open_config_folder(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR)))

    def request_close(self) -> None:
        if self._shutting_down:
            return
        minimize_to_tray = self.settings.get_bool("minimize_to_tray", True)
        tray_available = self.tray is not None
        if minimize_to_tray and tray_available:
            if self.window is not None:
                self.window.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.notify(
                    APP_NAME,
                    "Still running in the tray — mappings stay active. Use the tray menu to exit.",
                )
            return
        self.quit_application()

    def quit_application(self) -> None:
        if self._shutting_down:
            return
        if self.settings.get_bool("confirm_exit", False):
            if self.window is not None:
                confirmed = ConfirmDialog.ask(
                    self.window,
                    "Exit Amue KeyFlow?",
                    "The keyboard engine will stop and your mappings will no longer run until you start the app again.",
                    "Exit",
                    danger=True,
                )
                if not confirmed:
                    return
        self.shutdown()
        if self.window is not None:
            self.window.force_close()
        self.app.quit()

    # -- caffeine ----------------------------------------------------------
    def set_caffeine(self, enabled: bool) -> None:
        """Keep the display awake; shared by the dashboard widget and the tray."""
        ok, message = self.power.set_enabled(bool(enabled))
        self.settings.set("caffeine_enabled", bool(enabled) and ok)
        self.notify(message, "success" if ok and enabled else ("error" if not ok else "info"))
        self._sync_widgets()
        if self.window is not None:
            self.window.refresh_current_page()

    # -- mapping operations ------------------------------------------------
    def _editor_parent(self):
        return self.window

    def create_mapping(self, override_id: str | None = None) -> None:
        dialog = MappingEditor(self, None, self._editor_parent(), override_id=override_id)
        dialog.center_on_parent()
        dialog.exec()
        self.refresh_state(full=True)

    def edit_mapping(self, mapping_id: str) -> None:
        mapping = self.db.get_mapping(mapping_id)
        if mapping is None:
            self.notify("That mapping no longer exists.", "error")
            self.refresh_state(full=True)
            return
        dialog = MappingEditor(self, mapping, self._editor_parent())
        dialog.center_on_parent()
        dialog.exec()
        self.refresh_state(full=True)

    def save_mapping(self, mapping: Mapping) -> bool:
        try:
            self.db.save_mapping(mapping)
        except Exception as exc:
            log.exception("Saving mapping failed")
            self.notify(f"The mapping could not be saved: {exc}", "error")
            return False
        self.refresh_state(full=True)
        self.notify("Mapping saved.", "success")
        return True

    def duplicate_mapping(self, mapping_id: str) -> None:
        mapping = self.db.get_mapping(mapping_id)
        if mapping is None:
            return
        try:
            clone = mapping.clone()
            clone.name = f"{mapping.name or mapping.input_display} copy"[:80]
            clone.is_enabled = False
            self.db.save_mapping(clone)
        except Exception as exc:
            log.exception("Duplicating mapping failed")
            self.notify(f"Could not duplicate the mapping: {exc}", "error")
            return
        self.refresh_state(full=True)
        self.notify("Mapping duplicated (disabled). Edit its trigger, then enable it.", "info")

    def delete_mapping(self, mapping_id: str) -> None:
        mapping = self.db.get_mapping(mapping_id)
        if mapping is None:
            return
        if self.settings.get_bool("confirm_delete", True) and self.window is not None:
            confirmed = ConfirmDialog.ask(
                self.window,
                "Delete mapping?",
                f"\u201c{mapping.name or mapping.input_display}\u201d will be permanently removed from "
                f"{'this app override' if mapping.is_override else 'this profile'}.",
                "Delete",
                danger=True,
            )
            if not confirmed:
                return
        self.db.delete_mapping(mapping_id)
        self.refresh_state(full=True)
        self.notify("Mapping deleted.", "info")

    def set_mapping_enabled(self, mapping: Mapping, enabled: bool) -> None:
        mapping.is_enabled = enabled
        try:
            self.db.save_mapping(mapping)
        except Exception:
            log.exception("Could not toggle mapping")
            self.notify("The mapping state could not be saved.", "error")
        QTimer.singleShot(0, lambda: self.refresh_state(full=True))

    def set_all_mappings_enabled(self, enabled: bool) -> None:
        self.db.set_mappings_enabled(self.profiles.active_id, enabled)
        self.refresh_state(full=True)
        self.notify(f"All mappings in “{self.profiles.active.name}” {'enabled' if enabled else 'disabled'}.", "info")

    # -- app overrides -----------------------------------------------------
    def mappings_for_scope(self, override_id: str | None) -> list[Mapping]:
        if override_id:
            return self.db.list_override_mappings(override_id)
        return self.profiles.active_mappings()

    def mappings_for_engine(self) -> list[Mapping]:
        """Override mappings first: the engine index keeps the first match."""
        override = self.active_override()
        if override is not None:
            return self.db.list_override_mappings(override.id) + self.profiles.active_mappings()
        return self.profiles.active_mappings()

    def all_mappings(self) -> list[Mapping]:
        mappings = self.profiles.active_mappings()
        for override in self.db.list_app_overrides():
            mappings.extend(self.db.list_override_mappings(override.id))
        return mappings

    def active_override(self) -> AppOverride | None:
        override = self._active_override
        return override if override is not None and override.is_enabled else None

    def _sync_engine_scope(self, force: bool = False) -> None:
        override = self.active_override()
        signature = (self.profiles.active_id, override.id if override else "")
        if not force and signature == self._engine_scope:
            self._update_override_indicator()
            return
        self._engine_scope = signature
        self.engine.set_mappings(self.mappings_for_engine())
        self._update_override_indicator()

    def _update_override_indicator(self) -> None:
        if self.window is None:
            return
        override = self.active_override()
        fresh = self.db.get_app_override(override.id) if override else None
        self.window.sidebar.set_override(fresh)

    def add_app_override(self) -> str | None:
        dialog = AppOverrideDialog(self, self._editor_parent())
        dialog.center_on_parent()
        if dialog.exec() != dialog.Accepted or not dialog.result:
            return None
        try:
            override = self.db.create_app_override(*dialog.result)
        except ValueError as exc:
            self.notify(str(exc), "error")
            return None
        self.refresh_state(full=True)
        self.notify(f"App override for {override.executable} created.", "success")
        return override.id

    def delete_app_override(self, override_id: str) -> None:
        override = self.db.get_app_override(override_id)
        if override is None:
            return
        count = len(self.db.list_override_mappings(override_id))
        if self.window is not None and not ConfirmDialog.ask(
            self.window,
            "Delete app override?",
            f"\u201c{override.executable}\u201d returns to your normal profile behaviour and "
            f"{count} override mapping(s) are removed.",
            "Delete override",
            danger=True,
        ):
            return
        self.db.delete_app_override(override_id)
        if self._active_override is not None and self._active_override.id == override_id:
            self._active_override = None
        self.refresh_state(full=True)
        self.notify("App override deleted.", "info")

    def set_app_override_enabled(self, override_id: str, enabled: bool) -> None:
        override = self.db.get_app_override(override_id)
        if override is None:
            return
        override.is_enabled = bool(enabled)
        self.db.update_app_override(override)
        if self._active_override is not None and self._active_override.id == override_id:
            self._active_override = override
        self.refresh_state(full=True)
        self.notify(
            "App override enabled." if enabled else "App override disabled \u2014 the profile applies normally.",
            "info",
        )

    # -- engine operations -------------------------------------------------
    def set_mappings_enabled(self, enabled: bool) -> None:
        self.settings.set("mappings_enabled", enabled)
        self.engine.set_mappings_enabled(enabled)
        if enabled and not self.engine.running:
            self.start_engine()
        self._conflict_cache = set(conflicts_by_mapping(self.profiles.active_mappings()))
        self.refresh_state()
        self.notify("Mappings enabled." if enabled else "Mappings disabled — keys pass through.", "success" if enabled else "info")

    def set_paused(self, paused: bool) -> None:
        if paused and not self.engine.running:
            self.start_engine()
        self.engine.set_paused(paused)
        if not paused and not self.engine.running:
            self.start_engine()
        self._sync_widgets()
        self.refresh_state()
        self.notify("Mappings paused." if paused else "Mappings resumed.", "info")

    def toggle_pause(self) -> None:
        self.set_paused(not self.engine.paused)

    def set_engine_enabled(self, enabled: bool) -> None:
        self.settings.set("engine_enabled", enabled)
        if enabled:
            self.start_engine()
        else:
            self.engine.stop()
        self.refresh_state(full=True)
        self.notify(
            "Keyboard engine running." if enabled else "Keyboard engine stopped — your keyboard is normal.",
            "success" if enabled else "info",
        )

    def emergency_stop(self) -> None:
        self.safety.emergency_stop("Emergency stop requested")
        self.refresh_state()

    def recover_engine(self) -> bool:
        ok = self.safety.recover()
        self.refresh_state(full=True)
        return ok

    # -- startup -----------------------------------------------------------
    def set_start_with_windows(self, enabled: bool) -> tuple[bool, str]:
        if enabled:
            ok, message = self.startup.enable()
        else:
            ok, message = self.startup.disable()
        if ok:
            self.settings.set("start_with_windows", enabled)
        return ok, message

    # -- profiles ----------------------------------------------------------
    def switch_profile(self, profile_id: str) -> None:
        try:
            profile = self.profiles.switch(profile_id)
        except ValueError as exc:
            self.notify(str(exc), "error")
            return
        self.refresh_state(full=True)
        self.notify(f"Switched to profile “{profile.name}”.", "success")

    def _on_foreground_app(self, executable: str) -> None:
        """Layer app overrides on top of the active profile and apply app rules."""
        if self._shutting_down or not executable:
            return
        self._active_override = self.db.app_override_for_executable(executable)
        self._sync_engine_scope()

        if not self.settings.get_bool("auto_switch_profiles", True):
            return
        # Never change profiles underneath an open dialog (editor, recorder, …).
        if QApplication.activeModalWidget() is not None:
            return
        profile = self.profiles.profile_for_app(executable)
        if profile is None or profile.id == self.profiles.active_id:
            return
        try:
            self.profiles.switch(profile.id)
        except ValueError:
            return
        log.info("Auto-switched to profile “%s” for %s", profile.name, executable)
        if self.window is not None and self.window.isVisible():
            self.notify(f"Profile “{profile.name}” · {executable}", "info")

    def open_app_rules(self, profile_id: str) -> None:
        profile = self.db.get_profile(profile_id)
        if profile is None:
            return
        dialog = AppRulesDialog(self, profile, self._editor_parent())
        dialog.center_on_parent()
        dialog.exec()
        self.refresh_state(full=True)

    def create_profile(self) -> None:
        result = ProfileDialog.ask(self._editor_parent(), "New profile")
        if not result:
            return
        name, description = result
        try:
            profile = self.profiles.create(name, description)
        except ValueError as exc:
            self.notify(str(exc), "error")
            return
        self.refresh_state(full=True)
        self.notify(f"Profile “{profile.name}” created.", "success")

    def rename_profile(self, profile_id: str) -> None:
        profile = self.db.get_profile(profile_id)
        if profile is None:
            return
        result = ProfileDialog.ask(self._editor_parent(), "Rename profile", profile.name, profile.description)
        if not result:
            return
        name, description = result
        try:
            self.profiles.rename(profile_id, name, description)
        except ValueError as exc:
            self.notify(str(exc), "error")
            return
        self.refresh_state(full=True)
        self.notify("Profile updated.", "success")

    def duplicate_profile(self, profile_id: str) -> None:
        try:
            profile = self.profiles.duplicate(profile_id)
        except ValueError as exc:
            self.notify(str(exc), "error")
            return
        self.refresh_state(full=True)
        self.notify(f"Profile duplicated as “{profile.name}”.", "success")

    def delete_profile(self, profile_id: str) -> None:
        profile = self.db.get_profile(profile_id)
        if profile is None:
            return
        if profile_id == self.profiles.active_id:
            self.notify("Switch to another profile before deleting this one.", "error")
            return
        if self.window is not None and not ConfirmDialog.ask(
            self.window,
            "Delete profile?",
            f"“{profile.name}” and all of its mappings will be permanently removed.",
            "Delete profile",
            danger=True,
        ):
            return
        try:
            self.profiles.delete(profile_id)
        except ValueError as exc:
            self.notify(str(exc), "error")
            return
        self.refresh_state(full=True)
        self.notify("Profile deleted.", "info")

    # -- import / export ---------------------------------------------------
    def _export_entries(self, profiles) -> list[tuple]:
        return [(profile, self.db.list_mappings(profile.id)) for profile in profiles]

    def _export_rules(self, profiles) -> dict[str, list[str]]:
        return {profile.id: [rule.executable for rule in self.db.list_app_rules(profile.id)] for profile in profiles}

    def _export_overrides(self) -> list[tuple]:
        return [
            (override, self.db.list_override_mappings(override.id))
            for override in self.db.list_app_overrides()
        ]

    def export_profile(self, profile_id: str) -> None:
        profile = self.db.get_profile(profile_id)
        if profile is None:
            return
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        suggested = str(EXPORT_DIR / f"{_safe_name(profile.name)}.json")
        path, _ = QFileDialog.getSaveFileName(
            self.window, "Export profile", suggested, "Amue KeyFlow configuration (*.json)"
        )
        if not path:
            return
        try:
            write_export(path, self._export_entries([profile]), self._export_rules([profile]))
        except OSError as exc:
            self.notify(f"Could not write the file: {exc}", "error")
            return
        self.notify(f"Profile exported to {Path(path).name}.", "success")

    def export_all(self) -> None:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        suggested = str(EXPORT_DIR / "amue-keyflow-backup.json")
        path, _ = QFileDialog.getSaveFileName(
            self.window, "Export all profiles", suggested, "Amue KeyFlow configuration (*.json)"
        )
        if not path:
            return
        try:
            profiles = self.profiles.profiles()
            write_export(
                path,
                self._export_entries(profiles),
                self._export_rules(profiles),
                self._export_overrides(),
            )
        except OSError as exc:
            self.notify(f"Could not write the file: {exc}", "error")
            return
        self.notify(f"Configuration exported to {Path(path).name}.", "success")

    def import_configuration(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.window, "Import configuration", str(EXPORT_DIR), "Amue KeyFlow configuration (*.json)"
        )
        if not path:
            return
        try:
            payload = load_payload(path)
            parsed = parse_payload(payload)
            parsed_overrides = parse_overrides(payload)
        except ImportValidationError as exc:
            MessageSheet.show_message(self.window, "Import failed", str(exc))
            return
        except Exception as exc:  # pragma: no cover - unexpected I/O failure
            log.exception("Import failed")
            MessageSheet.show_message(self.window, "Import failed", f"The file could not be read: {exc}")
            return

        profile_count = len(parsed)
        mapping_count = sum(len(mappings) for _, mappings in parsed)
        dialog = ImportDialog(
            self.window, profile_count, mapping_count, Path(path).name, len(parsed_overrides)
        )
        dialog.center_on_parent()
        if dialog.exec() != dialog.Accepted or not dialog.mode:
            return

        mode = dialog.mode
        if mode == "replace":
            if self.window is not None and not ConfirmDialog.ask(
                self.window,
                "Replace the current configuration?",
                "Every existing profile, mapping and app override will be deleted and replaced by the "
                "imported file. A database backup is created first.",
                "Replace everything",
                danger=True,
            ):
                return
            try:
                self.db.backup_database("pre-import")
            except Exception:
                log.exception("Pre-import backup failed")

        try:
            summary = import_payload(self.db, payload, mode=mode)
        except ImportValidationError as exc:
            MessageSheet.show_message(self.window, "Import failed", str(exc))
            return
        except Exception as exc:  # pragma: no cover
            log.exception("Import failed")
            MessageSheet.show_message(self.window, "Import failed", f"The configuration could not be imported: {exc}")
            return

        if mode == "replace":
            self.profiles.reload()
        self.refresh_state(full=True)
        self.notify(summary.message, "success")

    # -- settings ----------------------------------------------------------
    def set_logging_level(self, level: str) -> None:
        self.settings.set("logging_level", level)
        configure_logging(level, self.settings.get_bool("debug_mode", False))

    def reset_settings(self) -> None:
        self.settings.reset()
        self.engine.configure()
        self.engine.set_mappings_enabled(self.settings.get_bool("mappings_enabled", True))
        self.apply_appearance()
        self.refresh_state(full=True)


def _safe_name(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in {" ", "-", "_"}).strip()
    return cleaned or "profile"


def _acquire_single_instance_lock():
    from PySide6.QtCore import QLockFile

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(DATA_DIR / "keyflow.lock"))
    lock.setStaleLockTime(15_000)
    if not lock.tryLock(200):
        return None
    return lock


def run() -> int:
    if sys.platform == "win32":
        try:
            ctypes_windll = __import__("ctypes").windll
            ctypes_windll.shell32.SetCurrentProcessExplicitAppUserModelID("Amue.KeyFlow.1")
        except Exception:
            pass

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("Amue")
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")

    lock = _acquire_single_instance_lock()
    if lock is None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(
            None,
            APP_NAME,
            f"{APP_NAME} is already running. Look for it in the system tray.",
        )
        return 0

    family = theme.load_fonts()
    app.setFont(theme.base_font(family, 10))

    from app.ui.main_window import MainWindow

    controller = AppController(app)
    window = MainWindow(controller)
    controller.attach_window(window)

    tray = TrayManager(controller)
    controller.attach_tray(tray)
    tray.show()
    tray.refresh_state()

    window.refresh_current_page()
    controller.start_engine()
    controller.start_voice()
    controller.foreground.start()
    window.refresh_all_pages()

    autostart = "--autostart" in sys.argv
    start_hidden = controller.settings.get_bool("launch_minimized", False) or (
        autostart and controller.settings.get("startup_behavior", "tray") == "tray"
    )
    if start_hidden:
        log.info("Starting minimized to the system tray")
    else:
        window.show()
        window.raise_()

    code = app.exec()
    controller.shutdown()
    lock.unlock()
    return code
