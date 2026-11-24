"""Render every page in both themes for visual review.

Run with:  python tools/capture_review.py
Images are written to .ui-review/ (override with AMUE_REVIEW_OUT).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA = tempfile.mkdtemp(prefix="keyflow-review-")
os.environ["AMUE_KEYFLOW_DATA_DIR"] = DATA
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.application import AppController  # noqa: E402
from app.database.models import Mapping, new_id, utc_now  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.mapping_editor import MappingEditor  # noqa: E402

OUT = Path(os.environ.get("AMUE_REVIEW_OUT", ROOT / ".ui-review"))
OUT.mkdir(parents=True, exist_ok=True)

PAGES = ("dashboard", "mapper", "tester", "voice", "profiles", "activity", "settings")


def render(widget, name: str) -> None:
    app = QApplication.instance()
    for _ in range(3):
        app.processEvents()
    pixmap = widget.grab()
    path = OUT / f"{name}.png"
    pixmap.save(str(path))
    print(f"rendered {path} ({pixmap.width()}x{pixmap.height()})")


def seed(controller: AppController) -> None:
    profile = controller.profiles.active
    rows = [
        ("Caps Lock to Home", "capslock", {"key": "home"}, "key", True),
        ("Copy", "f14", {"mods": ["ctrl"], "key": "c"}, "shortcut", True),
        ("Paste", "f15", {"mods": ["ctrl"], "key": "v"}, "shortcut", True),
        ("Volume up", "f16", {"action": "volumeup"}, "action", True),
        ("Screenshot", "f17", {"action": "screenshot"}, "action", False),
        ("Open terminal", "f18", {"command": "wt.exe"}, "launch", True),
    ]
    for name, key, output, kind, enabled in rows:
        controller.db.save_mapping(
            Mapping(
                id=new_id(),
                profile_id=profile.id,
                name=name,
                input_config={"mods": ["alt", "shift"] if key == "f18" else [], "key": key},
                output_config=output,
                mapping_type=kind,
                trigger_behavior="press",
                is_enabled=enabled,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
    controller.refresh_state(full=True)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    family = theme.load_fonts()
    app.setFont(theme.base_font(family, 10))
    print(f"UI font: {family}")

    controller = AppController(app)
    seed(controller)
    window = MainWindow(controller)
    controller.attach_window(window)
    window.resize(1360, 860)
    window.show()
    app.processEvents()

    for theme_name in ("dark", "light"):
        controller.settings.set("theme", theme_name)
        controller.apply_appearance()
        for page in PAGES:
            window.navigate(page)
            if page == "tester":
                tester = window.pages["tester"]
                tester.simulate(0x41, 0x1E)  # A, drawn on the layout
                tester.simulate(0xAF, 0x30, True)  # Volume up, outside the layout
                tester.simulate(0x14, 0x3A)  # Caps Lock, mapped in the seeded profile
            render(window, f"{theme_name}-{page}")

        window.navigate("mapper")
        editor = MappingEditor(controller, None, window)
        editor.show()
        render(editor, f"{theme_name}-editor")
        editor.reject()

    controller.engine.stop()
    window.force_close()
    controller.shutdown()
    print("REVIEW CAPTURE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
