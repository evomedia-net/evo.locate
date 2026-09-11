"""The guard that stops a release zip from lying about what is inside it.

A release archive is named after a version, and people trust that name. Two
ways it can lie, and both were reachable:

  1. The version is already tagged and the tree has moved on. Rebuilding then
     produces an archive named for a tag it no longer contains. This is not
     hypothetical - it happened in the sibling project, where ``--force``
     quietly replaced a tagged release's zip with newer content.
  2. The tree is dirty. The zip is built from working-tree files, so
     uncommitted edits land in a published artefact nobody reviewed.

The unit tests below are the cheap half and prove little on their own: the
failure worth preventing was not faulty logic, it was a script that consulted
none. So the half that matters builds a real throwaway repository, lays a real
tag, moves the tree, and runs the actual ``scripts/release.py`` against it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from release import release_guard  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "release.py"
VERSION = "v1.2.3.4.5"


# ── the decision ────────────────────────────────────────────────────────────

def test_a_clean_tree_at_an_untagged_version_is_fine():
    assert release_guard(VERSION, tag_exists=False, tree_differs=False, dirty=[]) is None


def test_rebuilding_a_tagged_version_is_fine_when_the_tree_still_matches():
    # Losing a release file and regenerating it byte-for-byte is legitimate;
    # the zips here are deterministic precisely so that this works.
    assert release_guard(VERSION, tag_exists=True, tree_differs=False, dirty=[]) is None


def test_a_tagged_version_whose_tree_has_moved_is_refused():
    reason = release_guard(VERSION, tag_exists=True, tree_differs=True, dirty=[])
    assert reason and "already tagged" in reason and VERSION in reason


def test_a_dirty_tree_is_refused_and_the_files_are_named():
    reason = release_guard(VERSION, tag_exists=False, tree_differs=False,
                           dirty=["app/main.py", "README.md"])
    assert reason and "app/main.py" in reason and "README.md" in reason


def test_a_long_dirty_list_is_summarised():
    reason = release_guard(VERSION, tag_exists=False, tree_differs=False,
                           dirty=[f"f{i}.py" for i in range(12)])
    assert "and 9 more" in reason
    assert "f11.py" not in reason


def test_the_dirty_tree_is_reported_first_when_both_apply():
    # It is the one the person can act on immediately.
    reason = release_guard(VERSION, tag_exists=True, tree_differs=True, dirty=["a.py"])
    assert "uncommitted" in reason


# ── the real script, against a real repository ──────────────────────────────

def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "-c", "core.autocrlf=false", *args],
        cwd=repo, capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A miniature repo shaped like this one, so release.py's path maths lines up."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "release.py")
    (tmp_path / "build-version.json").write_text(json.dumps({"version": VERSION}) + "\n",
                                                 encoding="utf-8")
    (tmp_path / "README.md").write_text("first\n", encoding="utf-8")
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "initial")
    git(tmp_path, "tag", "-a", VERSION, "-m", VERSION)
    return tmp_path


def release(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(repo / "scripts" / "release.py"), *args],
                          cwd=repo, capture_output=True, text=True)


def test_it_builds_when_the_tree_is_clean_and_matches_the_tag(repo: Path):
    out = release(repo)
    assert "Refusing" not in out.stdout, out.stdout
    assert out.returncode == 0, out.stdout + out.stderr
    assert (repo / "releases" / f"evo.locate-{VERSION}.zip").exists()


def test_it_refuses_once_the_source_has_moved_past_the_tag(repo: Path):
    (repo / "README.md").write_text("second\n", encoding="utf-8")
    git(repo, "commit", "-am", "more work")

    out = release(repo)
    assert out.returncode == 1
    assert "Refusing to build" in out.stdout and "already tagged" in out.stdout
    assert not (repo / "releases" / f"evo.locate-{VERSION}.zip").exists()


def test_force_does_not_get_past_it(repo: Path):
    # The bug being fixed: --force was enough to overwrite a released archive
    # with contents from a different tree.
    assert release(repo).returncode == 0
    (repo / "README.md").write_text("second\n", encoding="utf-8")
    git(repo, "commit", "-am", "more work")

    out = release(repo, "--force")
    assert out.returncode == 1
    assert "Refusing to build" in out.stdout


def test_it_refuses_an_uncommitted_edit(repo: Path):
    (repo / "README.md").write_text("not committed\n", encoding="utf-8")
    out = release(repo)
    assert out.returncode == 1
    assert "uncommitted changes" in out.stdout and "README.md" in out.stdout


def test_it_still_builds_when_only_releases_has_moved(repo: Path):
    # A version's zip and digest are committed AFTER its tag is laid, so they
    # are always "different from the tag". Counting them would make the guard
    # refuse every genuine release - the way a check becomes noise, then gets
    # switched off.
    (repo / "releases").mkdir()
    (repo / "releases" / "old.zip").write_bytes(b"pretend archive\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "chore: the release artefacts")

    out = release(repo)
    assert "Refusing" not in out.stdout, out.stdout
    assert out.returncode == 0


def test_allow_mismatch_overrides_and_says_so(repo: Path):
    (repo / "README.md").write_text("second\n", encoding="utf-8")
    git(repo, "commit", "-am", "more work")

    out = release(repo, "--allow-mismatch")
    assert out.returncode == 0, out.stdout + out.stderr
    assert "WARNING (--allow-mismatch)" in out.stdout
    assert "already tagged" in out.stdout


def test_digest_only_is_not_blocked_by_the_guard(repo: Path):
    # --digest-only never rebuilds a zip, so neither refusal applies to it -
    # and it is the one command you reach for when the tree HAS moved on.
    assert release(repo).returncode == 0
    (repo / "README.md").write_text("second\n", encoding="utf-8")
    git(repo, "commit", "-am", "more work")
    (repo / "releases" / "evo.locate-v0.0.0.9.9.zip.sha256").unlink(missing_ok=True)

    out = release(repo, "--digest-only")
    assert out.returncode == 0, out.stdout + out.stderr
    assert "Refusing" not in out.stdout
