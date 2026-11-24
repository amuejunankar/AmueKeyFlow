"""Build a single-page HTML gallery from the .ui-review screenshots."""

from __future__ import annotations

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".ui-review"

SCREENS = [
    ("dashboard", "Dashboard"),
    ("mapper", "Key Mapper"),
    ("tester", "Key Tester"),
    ("voice", "Voice FX"),
    ("profiles", "Profiles"),
    ("activity", "Activity"),
    ("settings", "Settings"),
    ("editor", "Mapping editor"),
]


def img(name: str) -> str:
    data = (OUT / f"{name}.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode()


def main() -> None:
    parts = [
        """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Amue KeyFlow 1.4.0 UI review</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 28px 32px 64px; background: #0b0d18; color: #e8ebf5;
         font: 14px/1.5 "Segoe UI", system-ui, sans-serif; }
  header { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; margin-bottom: 6px; }
  h1 { font-size: 20px; margin: 0; letter-spacing: .2px; }
  .sub { color: #8b93b0; font-size: 13px; }
  .hint { margin: 10px 0 26px; padding: 10px 14px; border: 1px solid #262b45; border-radius: 10px;
          background: #11142a; color: #aab2cc; font-size: 13px; }
  nav { position: sticky; top: 0; z-index: 5; display: flex; gap: 8px; flex-wrap: wrap;
        padding: 10px 0 14px; background: linear-gradient(#0b0d18 70%, rgba(11,13,24,0)); }
  nav a { color: #cfd5ea; text-decoration: none; font-size: 12.5px; padding: 6px 11px;
          border: 1px solid #2a3050; border-radius: 999px; background: #141833; }
  nav a:hover { border-color: #7c5cff; color: #fff; }
  section { margin-bottom: 40px; }
  h2 { font-size: 15px; margin: 0 0 12px; color: #dfe3f2; letter-spacing: .04em; text-transform: uppercase; }
  .pair { display: grid; grid-template-columns: repeat(auto-fit, minmax(520px, 1fr)); gap: 18px; }
  figure { margin: 0; border: 1px solid #262b45; border-radius: 12px; overflow: hidden; background: #12162b; }
  figcaption { padding: 8px 12px; font-size: 12px; letter-spacing: .08em; text-transform: uppercase;
               color: #9aa3c0; border-bottom: 1px solid #262b45; }
  img { display: block; width: 100%; height: auto; }
</style></head><body>
<header><h1>Amue KeyFlow 1.4.0 — UI review</h1><span class="sub">installed build, 1360 × 860</span></header>
<div class="hint">Every page in dark (left) and light (right). Tell me the page + what looks off
(e.g. “Dashboard: header text sits on top of the mapping rows”) and I will fix exactly that.</div>
<nav>"""
    ]
    for key, label in SCREENS:
        parts.append(f'<a href="#{key}">{label}</a>')
    parts.append("</nav>")
    for key, label in SCREENS:
        parts.append(f'<section id="{key}"><h2>{label}</h2><div class="pair">')
        for theme_name in ("dark", "light"):
            parts.append(
                f'<figure><figcaption>{theme_name}</figcaption>'
                f'<img alt="{label} {theme_name}" src="{img(f"{theme_name}-{key}")}"></figure>'
            )
        parts.append("</div></section>")
    parts.append("</body></html>")
    path = OUT / "review.html"
    path.write_text("".join(parts), encoding="utf-8")
    print(f"wrote {path} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
