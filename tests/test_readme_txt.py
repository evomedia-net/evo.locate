# Evomedia.net evo.locate — https://github.com/evomedia-net/evo.locate
# Created by Kelly Michels · dev@evomedia.net
# Licensed under the MIT License. See LICENSE.

"""README.txt is generated from README.md; committing one without
regenerating the other ships a stale mirror. The script's --check mode is
the single source of truth for "in sync", so the test just runs it.

--check only proves a twin matches what the renderer produces, though. It says
nothing about whether the renderer produces the right thing, which is where
every defect in it has lived: a twin can be perfectly in sync and still have a
word missing from it. So the second half of this file pins the renderer itself
against fixtures - each case below is a shape that came out wrong before it was
fixed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT / "scripts"))
from readme_txt import render  # noqa: E402


def test_readme_txt_is_in_sync_with_readme_md():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "readme_txt.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ── the format ──────────────────────────────────────────────────────────────

def test_headings_are_underlined_and_links_keep_their_target():
    out = render("# One\n\n## Two\n\n### Three\n\n- **b** `c` [t](u)\n")
    assert "One\n===\n" in out
    assert "Two\n---\n" in out
    assert "Three\n~~~~~\n" in out
    assert "- b c t (u)" in out


def test_fence_markers_go_and_the_code_inside_is_indented():
    out = render("Run it:\n\n```bash\npytest -q\n```\n")
    assert "    pytest -q" in out
    assert "```" not in out


# ── the renderer's own defects ──────────────────────────────────────────────

def test_inline_code_is_content_not_markup():
    """What is inside backticks is the thing being documented, not markup.

    SECURITY.md names the header family ``X-Forwarded-*``. A sibling fleet
    document names a pair of input files ``Civil Parties*JWEB*.txt``, and the
    italic rule ate those asterisks, gluing two words into "PartiesJWEB".
    """
    assert "X-Forwarded-*" in render("blanks `X-Real-IP` and `X-Forwarded-*` first\n")
    assert "Parties*JWEB*.txt" in render("`Civil Parties*JWEB*.txt` is a file\n")
    assert "<a href=\"x\">" in render("credit DB-IP with `<a href=\"x\">`\n")
    assert "a~~b~~c" in render("run `a~~b~~c` now\n")


def test_raw_html_leaves_only_its_words():
    """A tag contributes nothing; an <img> contributes its alt text.

    Matched against real element names and never ``</?\\w+>``, because these
    documents write placeholders the same way and deleting those would take
    words out of the twin - the one thing it must never do.
    """
    out = render('<picture><source srcset="a.png"><img src="b.png" alt="evomedia.net"></picture>\n')
    assert out.strip() == "evomedia.net"
    assert "<owner>/<repo>" in render("git clone https://host/<owner>/<repo>.git\n")


def test_a_link_whose_text_is_its_own_target_is_not_said_twice():
    """SECURITY.md links the address to itself through ``mailto:``.

    "dev@evomedia.net (mailto:dev@evomedia.net)" tells the reader nothing the
    second time. A different target is information, so that one keeps both.
    """
    mailto = render("email [dev@evomedia.net](mailto:dev@evomedia.net) now\n")
    assert mailto.strip() == "email dev@evomedia.net now"
    assert render("see [`CHECKSUMS.txt`](CHECKSUMS.txt)\n").strip() == "see CHECKSUMS.txt"
    elsewhere = render("see [the policy](https://e.example/p)\n")
    assert elsewhere.strip() == "see the policy (https://e.example/p)"


def test_strikethrough_markers_go():
    """Left in, they read as punctuation - and ``~`` is also what underlines a
    third-level heading, so a struck-out phrase looks like markup in the one
    file whose job is to have none."""
    assert render("~~old~~ -> new\n").strip() == "old -> new"
