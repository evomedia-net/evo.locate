"""Every release is downloadable and checkable.

This repo is public, and for an open-source repo the release zip with its
checksums is a requirement, not an optional extra - a project has to be
obtainable without cloning and verifiable once obtained.

It was not meeting that. Three zips existed for four tags, and not one of them
carried a checksum: no ``.sha256`` beside it, no ``CHECKSUMS.txt`` inside. So
these tests hold the rule rather than trusting anyone to remember it at release
time, which is exactly when it gets forgotten.

The three zips built before ``scripts/release.py`` are exempt from the INNER
manifest only. Rebuilding them would change bytes that are already published
and already named by their tags, which is worse than the gap it closes; they
were given the download digest they were missing and otherwise left alone.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RELEASES = REPO / "releases"

#: Built before scripts/release.py existed. Exempt from the inner manifest, and
#: this list must never grow: anything newer is built by the script.
PRE_SCRIPT = {"evo.locate-v0.0.0.1.1.zip", "evo.locate-v0.0.0.1.2.zip", "evo.locate-v0.0.0.1.3.zip"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def zips() -> list[Path]:
    return sorted(RELEASES.glob("*.zip"))


def current_version() -> str:
    return json.loads((REPO / "build-version.json").read_text(encoding="utf-8"))["version"]


def tags() -> list[str]:
    out = subprocess.run(["git", "tag", "--list", "v*"], cwd=REPO,
                         capture_output=True, text=True)
    return [t for t in out.stdout.split() if re.fullmatch(r"v\d+(\.\d+){4}", t)]


def test_there_is_a_release_for_every_tag():
    missing = [t for t in tags() if not (RELEASES / f"evo.locate-{t}.zip").exists()]
    assert not missing, f"tags with no release zip: {missing}"


def test_the_current_version_has_a_release():
    """Once it is tagged. Before that, it is mid-release and owes nothing.

    This used to demand a zip for whatever build-version.json said, which
    deadlocked the release it was meant to protect: the version bump lands
    first, the tag goes on its merge commit, and scripts/release.py refuses to
    build an archive for a tag whose tree has moved - so at the moment the bump
    PR runs CI, the zip it is asked for cannot exist yet and could not be built
    if it did. The bump could never go green.

    The rule that actually matters is the one above: every TAG ships a zip. A
    stamped-but-untagged version has not shipped.
    """
    v = current_version()
    if v not in tags():
        return
    assert (RELEASES / f"evo.locate-{v}.zip").exists(), (
        f"{v} is tagged but releases/ has no zip for it - "
        f"run: python scripts/release.py"
    )


@pytest.mark.parametrize("z", zips(), ids=lambda p: p.name)
def test_every_zip_has_a_digest_that_matches(z: Path):
    side = RELEASES / f"{z.name}.sha256"
    assert side.exists(), f"{z.name} has no .sha256 - run: python scripts/release.py --digest-only"
    raw = side.read_bytes()
    # sha256sum is line-ending sensitive: a CRLF checkout makes `sha256sum -c`
    # fail with "no properly formatted checksum lines found", so the file that
    # verifies a download would itself be broken by the checkout.
    assert b"\r" not in raw, f"{side.name} has CRLF line endings; sha256sum -c will reject it"
    text = raw.decode("utf-8")
    assert re.fullmatch(r"[0-9a-f]{64}  .+\n", text), f"{side.name} is not in sha256sum format: {text!r}"
    assert text.split()[0] == sha256_file(z), f"{side.name} does not match {z.name}"


@pytest.mark.parametrize("z", zips(), ids=lambda p: p.name)
def test_every_zip_opens_and_its_contents_are_intact(z: Path):
    with zipfile.ZipFile(z) as f:
        assert f.testzip() is None, f"{z.name} has a bad CRC"
        assert f.namelist(), f"{z.name} is empty"


@pytest.mark.parametrize("z", [p for p in zips() if p.name not in PRE_SCRIPT], ids=lambda p: p.name)
def test_new_releases_carry_the_inner_manifest(z: Path):
    with zipfile.ZipFile(z) as f:
        names = f.namelist()
        assert "CHECKSUMS.txt" in names, (
            f"{z.name} has no CHECKSUMS.txt - the download digest proves the archive "
            f"arrived intact, this proves the files did"
        )
        manifest = f.read("CHECKSUMS.txt").decode("utf-8")
        assert "\r" not in manifest, "CHECKSUMS.txt must be LF for sha256sum -c"
        listed = {line.split("  ", 1)[1] for line in manifest.strip().split("\n")}
        packaged = {n for n in names if n != "CHECKSUMS.txt"}
        assert listed == packaged, (
            f"{z.name}: the manifest and the archive disagree. "
            f"only in manifest: {sorted(listed - packaged)[:5]}, "
            f"only in archive: {sorted(packaged - listed)[:5]}"
        )
        # And the hashes are the files', not just plausible-looking hex.
        for line in manifest.strip().split("\n"):
            digest, name = line.split("  ", 1)
            assert hashlib.sha256(f.read(name)).hexdigest() == digest, f"{z.name}: {name} does not match its hash"


def test_the_exempt_list_never_grows():
    # Every exemption is a release nobody can verify after extracting. The list
    # is the three that predate the script; a fourth means someone packaged a
    # release by hand.
    assert len(PRE_SCRIPT) == 3
    assert all((RELEASES / n).exists() for n in PRE_SCRIPT), "an exempt zip is missing from releases/"
