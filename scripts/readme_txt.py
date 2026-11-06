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


#: HTML element names, so a tag can be told from prose that merely looks like
#: one. An allowlist and not `</?\w+>`, because these documents are full of
#: placeholders written the same way - <owner>/<repo>.git, <subject>.txt - and
#: deleting those would take words out of the twin, which is the one thing it
#: must never do.
_HTML = (
    r"</?(?:picture|source|img|div|span|br|p|a|table|thead|tbody|tfoot|tr|td|th"
    r"|details|summary|sup|sub|kbd|em|strong|code|pre|hr|h[1-6]|ul|ol|li"
    r"|blockquote|center|figure|figcaption|video|audio|iframe|small|b|i|u|s)"
    r"(?:\s[^<>]*)?/?>"
)


def _inline(text: str) -> str:
    """Strip the inline markup, keeping the words and the link targets.

    Inline code is lifted out FIRST and put back last. What is inside backticks
    is content, not markup, and running the emphasis rules over it corrupts it:
    SECURITY.md names the header family `X-Forwarded-*`, and a sibling fleet
    document a pair of input files as `Civil Parties*JWEB*.txt` - whose
    asterisks the italic rule ate, gluing two words into "PartiesJWEB". Same
    reasoning for the HTML rules: `<a>` written as an example is a word, not a
    tag.
    """
    code: list[str] = []

    def lift(match: re.Match) -> str:
        code.append(match.group(1))
        return f"\x00{len(code) - 1}\x00"

    def restore(s: str) -> str:
        return re.sub(r"\x00(\d+)\x00", lambda m: code[int(m.group(1))], s)

    text = re.sub(r"`([^`]+)`", lift, text)

    # An <img> carries its words in alt=, exactly as a markdown image does.
    text = re.sub(r"<img\b[^<>]*?\balt=[\"']([^\"']*)[\"'][^<>]*>", r"\1", text)
    text = re.sub(_HTML, "", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)  # images -> alt text

    def link(match: re.Match) -> str:
        """A link becomes "text (url)" - unless the text already IS the url.

        SECURITY.md links dev@evomedia.net to mailto:dev@evomedia.net, which
        read as "x (x)" - the same thing said twice, telling the reader nothing
        the second time. Compared after putting the code back, because such a
        link is usually written with backticks around its text.
        """
        shown, url = match.group(1), match.group(2)
        bare, target = restore(shown), restore(url)
        if bare == target or target == "mailto:" + bare:
            return shown
        return f"{shown} ({url})"

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)  # bold
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)  # italic
    # Strikethrough, same class as the two above. Left in place, its markers
    # read as punctuation AND collide with the "~" a third-level heading is
    # underlined with, so a struck-out phrase looks like markup in the one file
    # whose job is to have none. Safe unconditionally: no document here - or
    # anywhere in the fleet - uses "~~~" as a code fence, which is the one
    # construct this would disturb, and a tilde inside backticks is already
    # lifted out of reach.
    text = re.sub(r"~~([^~]+)~~", r"\1", text)  # strikethrough
    return restore(text)


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
            # h1 =, h2 -, h3 ~, deeper . - evo.polaris's md-txt.mjs, whose
            # CHANGELOG.txt is the fleet's changelog format (Kelly, 2026-10-27).
            out.append("=-~..."[len(heading.group(1)) - 1] * len(text))
            continue
        rendered = _inline(line)
        # A line that was only a tag - <picture>, </picture>, a bare <source> -
        # leaves nothing behind once the HTML rules have run. Emitting the
        # blank would turn one HTML block into a run of empty lines in the
        # middle of a paragraph.
        if line.strip() and not rendered.strip():
            continue
        out.append(rendered)
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
