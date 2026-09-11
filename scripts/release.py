"""Package this release as a downloadable, verifiable zip.

    python scripts/release.py              build releases/evo.locate-<version>.zip
    python scripts/release.py --force      rebuild the zip for this version
    python scripts/release.py --verify     re-check every zip in releases/
    python scripts/release.py --digest-only  write a .sha256 beside any zip missing one

An open-source project has to be obtainable without cloning, and checkable once
obtained. Two layers, on purpose:

    releases/<name>.zip.sha256    verifies the download arrived intact
    CHECKSUMS.txt inside the zip  verifies the files after extracting

Both are integrity checks, not signatures: the manifest travels in the same
archive as the files, so whoever can change one can change the other. They catch
a truncated download, a corrupted mirror and an accidental edit - not a forger.

WHAT GOES IN: everything git tracks, minus what a release should not carry.
Using ``git ls-files`` rather than a hand-kept list means the zip is exactly the
reviewed source, and a new file cannot be left out by forgetting to list it.

WHAT IT REFUSES TO DO
---------------------
A release archive is named after a version, and people trust that name. It will
not build one whose name would not describe its contents: not from a dirty tree
(the zip is built from working-tree files, so uncommitted edits would ship
inside it), and not for a version that is already tagged while the tree has
moved past it. ``--force`` overwrites a file; it does not license a mislabelled
one, so neither refusal yields to it. ``--allow-mismatch`` is the way past, and
someone has to type it.

WHY --digest-only EXISTS
------------------------
The three zips already published here were built before this script and carry no
checksum at all. Rebuilding them would change bytes that are already public and
already referenced by their tags, so they are left exactly as they are and given
the download digest they were missing. Only releases built from here carry the
inner manifest as well; the difference is visible in --verify, deliberately.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RELEASES = REPO / "releases"

#: Never package the packages, the caches, or anything a recipient rebuilds.
EXCLUDE_PREFIXES = ("releases/", ".github/")
EXCLUDE_NAMES = (".gitkeep",)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def version() -> str:
    import json
    v = json.loads((REPO / "build-version.json").read_text(encoding="utf-8")).get("version")
    if not v:
        sys.exit("build-version.json has no version.")
    return v


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    files = [p for p in out.split("\0") if p]
    keep = [p for p in files
            if not p.startswith(EXCLUDE_PREFIXES) and Path(p).name not in EXCLUDE_NAMES]
    if not keep:
        sys.exit("git ls-files returned nothing - is this a checkout?")
    return sorted(keep)


def write_digest(zip_path: Path) -> str:
    """sha256sum's own format: '<hex>  <name>', two spaces, LF."""
    digest = sha256_file(zip_path)
    (zip_path.parent / f"{zip_path.name}.sha256").write_bytes(
        f"{digest}  {zip_path.name}\n".encode("utf-8"))
    return digest


def release_guard(version_: str, tag_exists: bool, tree_differs: bool,
                  dirty: list[str]) -> str | None:
    """Why this archive would lie, or None if it would not.

    Pure on purpose: the combinations are the part worth testing, and they are
    unreachable through a real repository without building one per case.
    """
    if dirty:
        shown = ", ".join(dirty[:3])
        more = f" and {len(dirty) - 3} more" if len(dirty) > 3 else ""
        return (f"the tree has uncommitted changes ({shown}{more}), and the zip is built "
                f"from working-tree files - they would ship inside a published release. "
                f"Commit or stash them.")
    if tag_exists and tree_differs:
        return (f"{version_} is already tagged and this tree has moved past it, so the "
                f"archive would carry contents its own name does not describe. Bump the "
                f"version first, or check out {version_} to rebuild what was released.")
    return None


def repo_facts(version_: str) -> tuple[bool, bool, list[str]]:
    """(tag exists, tree differs from it, dirty tracked paths) - asked of git."""
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)

    tag_exists = git("rev-parse", "--verify", "--quiet", f"refs/tags/{version_}").returncode == 0
    # releases/ is excluded from both: a version's zip and digest are committed
    # AFTER its tag is laid, so they are the expected difference between the tag
    # and HEAD - and a half-written one is not a reason to refuse the next build.
    tree_differs = bool(
        tag_exists
        and git("diff", "--name-only", version_, "HEAD", "--", ".", ":(exclude)releases")
        .stdout.strip()
    )
    dirty = [line[3:].strip()
             for line in git("status", "--porcelain", "--untracked-files=no").stdout.splitlines()
             if len(line) > 3]
    return tag_exists, tree_differs, [d for d in dirty if not d.startswith("releases/")]


def build(force: bool, allow_mismatch: bool = False) -> int:
    v = version()
    name = f"evo.locate-{v}.zip"
    zip_path = RELEASES / name

    # Checked even under --force. Overwriting a file and publishing a
    # mislabelled one are different permissions; only the first is what
    # --force asks for.
    reason = release_guard(v, *repo_facts(v))
    if reason:
        if not allow_mismatch:
            print(f"\nRefusing to build releases/{name}: {reason}\n")
            print("Override with --allow-mismatch if you are certain.\n")
            return 1
        print(f"\n  WARNING (--allow-mismatch): {reason}\n")

    if zip_path.exists() and not force:
        print(f"\nreleases/{name} already exists. Use --force to rebuild, or --verify to check it.\n")
        return 1

    files = tracked_files()
    lines = []
    RELEASES.mkdir(parents=True, exist_ok=True)
    # Deterministic: sorted entries, and a fixed timestamp so two builds of the
    # same commit produce the same archive.
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            data = (REPO / rel).read_bytes()
            lines.append(f"{sha256_bytes(data)}  {rel}")
            info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
        manifest = ("\n".join(lines) + "\n").encode("utf-8")
        info = zipfile.ZipInfo("CHECKSUMS.txt", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        z.writestr(info, manifest)

    digest = write_digest(zip_path)
    size_kb = zip_path.stat().st_size // 1024
    print(f"\n  releases/{name}")
    print(f"    {len(files) + 1} files, {size_kb} kB")
    print(f"    CHECKSUMS.txt inside covers {len(files)} of them")
    print(f"  releases/{name}.sha256")
    print(f"    {digest}")
    print(f"\nVerify a download:      sha256sum -c {name}.sha256")
    print("Verify after unzipping: sha256sum -c CHECKSUMS.txt\n")
    return 0


def digest_only() -> int:
    """Give every zip a .sha256, without touching the zip itself."""
    zips = sorted(RELEASES.glob("*.zip"))
    if not zips:
        print("\nNo zips in releases/.\n")
        return 1
    made = 0
    for z in zips:
        side = RELEASES / f"{z.name}.sha256"
        if side.exists():
            print(f"  {z.name}  already has a digest")
            continue
        print(f"  {z.name}  -> {write_digest(z)[:16]}...")
        made += 1
    print(f"\n  {made} digest(s) written, {len(zips) - made} already present\n")
    return 0


def verify() -> int:
    zips = sorted(RELEASES.glob("*.zip"))
    if not zips:
        print("\nNo zips in releases/.\n")
        return 1
    bad = 0
    for z in zips:
        side = RELEASES / f"{z.name}.sha256"
        if not side.exists():
            print(f"  {z.name}  NO DIGEST")
            bad += 1
            continue
        expected = side.read_text(encoding="utf-8").split()[0]
        actual = sha256_file(z)
        with zipfile.ZipFile(z) as f:
            inner = "CHECKSUMS.txt" in f.namelist()
            corrupt = f.testzip()
        state = "OK " if expected == actual and not corrupt else "FAILED"
        if state.strip() == "FAILED":
            bad += 1
        print(f"  {z.name}  {state}  digest={'match' if expected == actual else 'MISMATCH'}"
              f"  crc={'ok' if not corrupt else 'BAD: ' + str(corrupt)}"
              f"  manifest inside={'yes' if inner else 'no (built before this script)'}")
    print(f"\n  {len(zips) - bad} of {len(zips)} verified\n")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="rebuild the zip for this version")
    ap.add_argument("--verify", action="store_true", help="check every zip in releases/")
    ap.add_argument("--digest-only", action="store_true",
                    help="write a .sha256 beside any zip missing one, without rebuilding it")
    ap.add_argument("--allow-mismatch", action="store_true",
                    help="build anyway when the tree is dirty or has moved past the tag")
    args = ap.parse_args()
    if args.verify:
        return verify()
    if args.digest_only:
        return digest_only()
    return build(args.force, args.allow_mismatch)


if __name__ == "__main__":
    raise SystemExit(main())
