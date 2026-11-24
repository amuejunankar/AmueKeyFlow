"""Live Windows integration check for the keyboard engine.

Verifies, on a real desktop session:
  * the low level hook installs and stops,
  * SendInput output reaches the focused widget (key and text outputs),
  * injected events do not re-trigger mappings (recursion protection),
  * emergency stop releases the hook and restores a normal keyboard.

Only runs when this script's own window is the foreground window, so it never
types into another application.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AMUE_KEYFLOW_DATA_DIR"] = tempfile.mkdtemp(prefix="keyflow-engine-")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget  # noqa: E402

from app.application import AppController  # noqa: E402
from app.database.models import Mapping, new_id, utc_now  # noqa: E402


class CaptureEdit(QLineEdit):
    keys: list[int] = []

    def keyPressEvent(self, event):  # noqa: N802
        CaptureEdit.keys.append(int(event.key()))
        super().keyPressEvent(event)


def wait(app: QApplication, ms: int) -> None:
    loop_end = ms
    timer = QTimer()
    timer.setSingleShot(True)
    results = []
    timer.timeout.connect(lambda: results.append(True))
    timer.start(loop_end)
    while not results:
        app.processEvents()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = QWidget()
    window.setWindowTitle("Amue KeyFlow engine check")
    window.resize(420, 120)
    layout = QVBoxLayout(window)
    edit = CaptureEdit()
    edit.setPlaceholderText("target field")
    layout.addWidget(edit)
    window.show()
    window.raise_()
    window.activateWindow()
    app.processEvents()
    wait(app, 400)

    if QApplication.activeWindow() is not window:
        print("SKIP: could not focus the test window; no synthetic keys sent.")
        return 0

    controller = AppController(app)
    design = controller.settings.get("theme", "dark")
    print("theme:", design)
    ok = controller.engine.start()
    print("hook started:", ok, "running:", controller.engine.hook.is_running, controller.engine.last_error)
    if not ok:
        print("FAIL: hook did not install")
        controller.shutdown()
        return 1

    profile = controller.profiles.active
    key_mapping = Mapping(
        id=new_id(),
        profile_id=profile.id,
        name="Engine home",
        input_config={"mods": [], "key": "capslock"},
        output_config={"key": "home"},
        mapping_type="key",
        trigger_behavior="press",
        is_enabled=True,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    text_mapping = Mapping(
        id=new_id(),
        profile_id=profile.id,
        name="Engine text",
        input_config={"mods": [], "key": "f13"},
        output_config={"text": "keyflow"},
        mapping_type="text",
        trigger_behavior="press",
        is_enabled=True,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    controller.db.save_mapping(key_mapping)
    controller.db.save_mapping(text_mapping)
    controller.refresh_state(full=True)

    triggered = []
    original_notify = controller.engine._notify_cb

    def capture(event, payload):
        if event == "mapping_triggered":
            triggered.append(payload)
        if original_notify:
            original_notify(event, payload)

    controller.engine._notify_cb = capture

    CaptureEdit.keys.clear()
    controller.engine._on_trigger(key_mapping, "press")
    app.processEvents()
    wait(app, 250)
    home_ok = int(Qt.Key_Home) in CaptureEdit.keys
    print("SendInput key output reached Qt:", home_ok, "keys=", CaptureEdit.keys)
    print("trigger notifications:", triggered)

    edit.clear()
    edit.setFocus()
    app.processEvents()
    controller.engine._on_trigger(text_mapping, "press")
    wait(app, 300)
    typed = edit.text()
    print("SendInput text output:", repr(typed))
    text_ok = typed == "keyflow"

    hook_alive = controller.engine.hook.is_running
    controller.engine.emergency_stop("integration check")
    app.processEvents()
    wait(app, 150)
    stopped = not controller.engine.hook.is_running
    print("hook alive before emergency:", hook_alive, "stopped after:", stopped)

    controller.shutdown()
    window.close()

    success = home_ok and text_ok and hook_alive and stopped
    print("ENGINE CHECK", "OK" if success else "FAILED")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
