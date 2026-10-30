"""Build static/icons.svg (a sprite) from the lucide-static icon folder.

Usage:
    npm pack lucide-static && tar xzf lucide-static-*.tgz
    uv run python scripts/build_icons.py package/icons
"""

import re
import sys
from pathlib import Path

ICONS = """
activity archive arrow-left arrow-right at-sign book-open brain calendar check
chevron-down chevron-left chevron-right circle-check circle-help clipboard-paste
clock cloud code copy database download external-link eye file-code file-plus
file-text file-up filter flask-conical folder git-commit-horizontal globe
hard-drive history house info layers layout-grid link list lock lock-open
menu moon notebook-pen pencil plus rotate-ccw save scale search server
shield-check sliders-horizontal sparkles sticky-note sun tag tags trash-2
triangle-alert undo-2 upload user user-plus users wand-sparkles x zap
""".split()

OUT = Path(__file__).resolve().parents[1] / "src/labcat/static/icons.svg"


def main(icon_dir: str) -> None:
    src = Path(icon_dir)
    symbols = []
    for name in ICONS:
        svg = (src / f"{name}.svg").read_text()
        body = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1).strip()
        body = re.sub(r"\s*\n\s*", "", body)
        symbols.append(f'<symbol id="i-{name}" viewBox="0 0 24 24">{body}</symbol>')
    OUT.write_text(
        "<!-- Icons: lucide-static (ISC license, see vendor/LUCIDE-LICENSE) -->\n"
        '<svg xmlns="http://www.w3.org/2000/svg">\n' + "\n".join(symbols) + "\n</svg>\n"
    )
    print(f"wrote {len(symbols)} icons to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
