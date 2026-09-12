# Evomedia.net evo.locate — https://github.com/evomedia-net/evo.locate
# Created by Kelly Michels · dev@evomedia.net
# Licensed under the MIT License. See LICENSE.

"""Render every root-level .md to a .txt twin with the markup removed.

The twins exist for terminals, pagers and anywhere markdown doesn't
render. They are generated - never edit one by hand:

    python scripts/readme_txt.py          # rewrite every twin
    python scripts/readme_txt.py --check  # exit 1 if any is out of sync

The test suite runs --check, so an edit that forgets to regenerate
fails CI rather than shipping a stale mirror.

Every .md at the repository root is covered, discovered rather than
listed: a hand-kept list is one more thing to forget, and the twin
that gets forgotten is the one nobody notices is stale. SECURITY.md
arrived after this script and a list would have missed it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _inline(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)  # images -> alt text
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)  # links -> text (url)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)  # bold
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)  # italic
    text = re.sub(r"`([^`]+)`", r"\1", text)  # inline code
    return text


def render(md: str) -> str:
    out: list[str] = []
    in_fence = False
    for line in md.splitlines():
        if line.lstrip().startswith("```"):
            # Drop the fence markers; the code itself stays, indented so it
            # still reads as a block without the backticks.
            in_fence = not in_fence
            continue
        if in_fence:
            out.append(("    " + line) if line else "")
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            text = _inline(heading.group(2))
            out.append(text)
            out.append(("=" if len(heading.group(1)) == 1 else "-") * len(text))
            continue
        out.append(_inline(line))
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def twins() -> list[Path]:
    """Every root-level .md that owes a .txt, in a stable order."""
    return sorted(ROOT.glob("*.md"))


def main() -> int:
    check = "--check" in sys.argv
    stale: list[str] = []
    for source_path in twins():
        rendered = render(source_path.read_text(encoding="utf-8"))
        target = source_path.with_suffix(".txt")
        if check:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            if current != rendered:
                stale.append(target.name)
            continue
        target.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"Wrote {target} ({len(rendered.splitlines())} lines)")
    if check:
        if stale:
            print(f"out of sync: {', '.join(stale)} - run: python scripts/readme_txt.py")
            return 1
        print(f"{len(twins())} twin(s) in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
