"""Generate the Amue KeyFlow application icon (.ico + .png) from code."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from app.ui.icons import app_icon  # noqa: E402

SIZES = [16, 24, 32, 48, 64, 128, 256]


def png_bytes(pixmap) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    data = bytes(buffer.data())
    buffer.close()
    return data


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    payload = b""
    for size, data in images:
        dimension = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII",
            dimension,
            dimension,
            0,
            0,
            1,
            32,
            len(data),
            offset,
        )
        payload += data
        offset += len(data)
    return header + entries + payload


def main() -> int:
    app = QGuiApplication(sys.argv)
    out_dir = ROOT / "app" / "resources" / "icons"
    out_dir.mkdir(parents=True, exist_ok=True)

    images: list[tuple[int, bytes]] = []
    for size in SIZES:
        pixmap = app_icon(size * 2).pixmap(size * 2, size * 2)
        pixmap.setDevicePixelRatio(2.0)
        images.append((size, png_bytes(app_icon(size).pixmap(size, size))))
        if size == 256:
            app_icon(512).pixmap(512, 512).save(str(out_dir / "amue_keyflow.png"), "PNG")

    ico = build_ico(images)
    (out_dir / "amue_keyflow.ico").write_bytes(ico)
    print(f"wrote {out_dir / 'amue_keyflow.ico'} ({len(ico)} bytes)")
    print(f"wrote {out_dir / 'amue_keyflow.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
