"""Headless UI smoke test: builds every page, edits a mapping and renders screenshots.

Run with:  python tools/smoke_ui.py
Screenshots are written to the directory given by AMUE_SMOKE_OUT (default: temp).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA = tempfile.mkdtemp(prefix="keyflow-smoke-")
os.environ["AMUE_KEYFLOW_DATA_DIR"] = DATA
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.application import AppController  # noqa: E402
from app.database.models import Mapping, new_id, utc_now  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.mapping_editor import MappingEditor  # noqa: E402

OUT = Path(os.environ.get("AMUE_SMOKE_OUT", tempfile.mkdtemp(prefix="keyflow-shots-")))
OUT.mkdir(parents=True, exist_ok=True)


def render(widget, name: str) -> None:
    app = QApplication.instance()
    app.processEvents()
    pixmap = widget.grab()
    path = OUT / f"{name}.png"
    pixmap.save(str(path))
    print(f"rendered {path} ({pixmap.width()}x{pixmap.height()})")


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    family = theme.load_fonts()
    app.setFont(theme.base_font(family, 10))
    print(f"UI font: {family}")

    controller = AppController(app)
    window = MainWindow(controller)
    controller.attach_window(window)
    window.resize(1360, 860)
    window.show()
    app.processEvents()

    profile = controller.profiles.active
    for index, key in enumerate(("capslock", "f14", "f15", "f16")):
        controller.db.save_mapping(
            Mapping(
                id=new_id(),
                profile_id=profile.id,
                name=["Home key", "Copy", "Paste", "Volume"][index],
                input_config={"mods": ["alt", "shift"] if index == 3 else [], "key": key},
                output_config=(
                    {"key": "home"}
                    if index == 0
                    else {"mods": ["ctrl"], "key": "c"}
                    if index == 1
                    else {"mods": ["ctrl"], "key": "v"}
                    if index == 2
                    else {"action": "volumeup"}
                ),
                mapping_type="key" if index == 0 else ("shortcut" if index < 3 else "action"),
                trigger_behavior="press",
                is_enabled=index != 3,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
    controller.refresh_state(full=True)
    app.processEvents()

    for key in ("dashboard", "mapper", "tester", "voice", "profiles", "activity", "settings"):
        window.navigate(key)
        if key == "tester":
            tester = window.pages["tester"]
            tester.simulate(0x41, 0x1E)  # A, drawn on the layout
            tester.simulate(0xAF, 0x30, True)  # Volume up, outside the layout
            tester.simulate(0x14, 0x3A)  # Caps Lock, mapped in the smoke profile
        render(window, f"dark-{key}")

    window.navigate("mapper")
    editor = MappingEditor(controller, None, window)
    editor.resize(editor.width(), editor.height())
    editor.show()
    app.processEvents()
    render(editor, "editor-dark")
    editor.name_input.setText("Smoke mapping")
    editor._set_type("macro")
    editor.macro_editor.steps = [
        {"type": "shortcut", "mods": ["ctrl"], "key": "a"},
        {"type": "wait", "ms": 300},
        {"type": "text", "text": "hello"},
    ]
    editor.macro_editor._render()
    app.processEvents()
    render(editor, "editor-macro")
    editor.reject()

    controller.engine.stop()
    controller.settings.set("theme", "light")
    app.processEvents()
    window.navigate("dashboard")
    render(window, "light-dashboard")
    window.navigate("mapper")
    render(window, "light-mapper")
    window.navigate("tester")
    window.pages["tester"].simulate(0x25, 0x4B, True)
    render(window, "light-tester")
    window.navigate("voice")
    render(window, "light-voice")
    controller.settings.set("theme", "dark")

    window.force_close()
    controller.shutdown()
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
