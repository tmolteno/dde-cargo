# Copyright (c) 2026 Tim Molteno (tim@elec.ac.nz)
"""Release orchestration for dde-cargo.

The cab files are NOT edited here: ``dde_cargo/{ddfacet,ddfacet-memory-plan,
killms-memory-plan}.yml`` and the two schema files are copied from the sibling
``../meerkat_imaging`` checkout (``cabs/``, override ``MEERKAT_REPO``) by
``invoke sync``, which ``release`` runs first.  The release is driven by those
cabs' image pins (which must equal the latest tags of the sibling ``../DDFacet``
and ``../killMS`` checkouts -- the release refuses otherwise):

    invoke version                     # current package + pinned/upstream tags
    invoke sync                        # copy the cabs from meerkat_imaging
    invoke sync --check                # verify dde_cargo/ matches meerkat_imaging
    invoke changelog                   # print the next release's changelog
    invoke changelog --allow-same      # ... even when no image tag moved
    invoke docs                        # regenerate docs/cabs.md
    invoke docs --check                # verify docs/cabs.md is current
    invoke release --dry-run           # show the complete release plan
    invoke release --part patch --yes  # sync, bump, test, build, tag, publish, release

``release`` performs the whole chain:

1. checks that meerkat_imaging's cab files are committed, reads the old
   (committed) DDFacet/killMS pins, the latest upstream release tags, and
   REFUSES when the cabs to be synced do not pin exactly those tags;
2. syncs the five cab files from meerkat_imaging into ``dde_cargo/`` and records
   the meerkat_imaging commit (``dde_cargo/meerkat-sync.json``);
3. generates a changelog section from the upstream commit history between the
   old and new tags plus meerkat_imaging's cab commits since the previously
   synced commit, and inserts it into ``CHANGELOG.md``;
4. bumps this package's version (patch by default; pass ``--part minor`` when
   a cab interface changed) and updates the image pins in the README;
5. regenerates ``docs/cabs.md`` from the packaged YAMLs;
6. runs ``uv lock``, the test suite and ``uv build``;
7. commits, creates an annotated ``vX.Y.Z`` tag and pushes both to GitHub --
   the tag push triggers ``.github/workflows/publish_pypi.yaml``;
8. waits for that workflow to succeed and verifies the version is on PyPI;
9. creates the GitHub release with the generated notes and the built wheel
   and sdist attached.

meerkat_imaging's own ``invoke release`` runs this task (``--part patch`` by
default, ``--dde-cargo-part``) after DDFacet and killMS are published.

Requirements: ``invoke`` and ``plumbum`` (the ``dev`` dependency group),
``uv``, ``gh`` authenticated to GitHub, and the sibling ``DDFacet``,
``killMS`` and ``meerkat_imaging`` checkouts (release tags in the first two).  The
path defaults can be overridden with ``DDFACET_REPO``, ``KILLMS_REPO`` and
``MEERKAT_REPO``.

The script never force-pushes and refuses to run on a dirty tree or when the
target tag/version already exists.  Use ``--dry-run`` first; it changes
nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import yaml
from invoke import task
from plumbum import FG, ProcessExecutionError, local

# Never let a release hang on an interactive credential or SSH prompt.
os.environ.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")

ROOT = Path(__file__).resolve().parent
DDFACET_REPO = Path(os.environ.get("DDFACET_REPO", ROOT.parent / "DDFacet")).expanduser()
KILLMS_REPO = Path(os.environ.get("KILLMS_REPO", ROOT.parent / "killMS")).expanduser()
MEERKAT_REPO = Path(os.environ.get("MEERKAT_REPO", ROOT.parent / "meerkat_imaging")).expanduser()
GH_REPO = os.environ.get("DDE_CARGO_GH_REPO", "tmolteno/dde-cargo")
REMOTE_URL = os.environ.get("DDE_CARGO_REMOTE", f"https://github.com/{GH_REPO}.git")
WORKFLOW = "publish_pypi.yaml"
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"
DDFACET_YML = ROOT / "dde_cargo" / "ddfacet.yml"
DDFACET_MP_YML = ROOT / "dde_cargo" / "ddfacet-memory-plan.yml"
KILLMS_MP_YML = ROOT / "dde_cargo" / "killms-memory-plan.yml"

PACKAGE_DIR = ROOT / "dde_cargo"
SYNC_RECORD = PACKAGE_DIR / "meerkat-sync.json"
# the files copied from meerkat_imaging/cabs into dde_cargo/ (never edited here)
SYNC_FILES = (
    "ddfacet.yml",
    "ddfacet-memory-plan.yml",
    "killms-memory-plan.yml",
    "ddfacet_stimela_inputs_schema.yml",
    "killms_stimela_schema.yml",
)

VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)+)$")
RELEASE_TAG_RE = re.compile(r"^v\d+(?:\.\d+)+$")
CREDENTIAL_HELPER = "credential.helper=!gh auth git-credential"


# ---------------------------------------------------------------------------
# command helpers


def _run(*argv: str, cwd: Path | None = None, stream: bool = False) -> str:
    """Run a command, streaming or capturing its output, with a clean error."""
    print("$", " ".join(argv))
    command = local[argv[0]][argv[1:]]
    try:
        with local.cwd(cwd or ROOT):
            if stream:
                command & FG
                return ""
            return command()
    except ProcessExecutionError as exc:
        stderr = (exc.stderr or "").strip().splitlines()
        detail = "\n".join(stderr[-8:]) if stderr else str(exc)
        raise RuntimeError(f"command failed: {' '.join(argv)}\n{detail}") from exc


def _git(repo: Path, *args: str) -> str:
    """Read-only git call in `repo` (no command echo)."""
    try:
        return local["git"][("-C", str(repo), *args)]().strip()
    except ProcessExecutionError as exc:
        stderr = (exc.stderr or "").strip().splitlines()
        detail = "\n".join(stderr[-8:]) if stderr else str(exc)
        raise RuntimeError(f"git {' '.join(args)} failed in {repo}\n{detail}") from exc


def _git_https(repo: Path, *args: str) -> str:
    """git call that authenticates over HTTPS with the gh credential helper."""
    return local["git"][("-C", str(repo), "-c", CREDENTIAL_HELPER, *args)]().strip()


def _remote_url(repo: Path) -> str | None:
    """The repo's origin as an HTTPS GitHub URL, when it is a GitHub remote."""
    try:
        url = _git(repo, "remote", "get-url", "origin")
    except RuntimeError:
        return None
    m = re.match(r"git@github\.com:(.+?)(?:\.git)?$", url)
    if m:
        return f"https://github.com/{m.group(1)}.git"
    if url.startswith("https://"):
        return url
    return None


def _require_tools(*names: str) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise RuntimeError(f"missing required command(s): {', '.join(missing)}")


# ---------------------------------------------------------------------------
# version and repository helpers


def _version_tuple(tag: str) -> tuple[int, ...]:
    m = VERSION_RE.fullmatch(tag.strip())
    if not m:
        raise RuntimeError(f"not a release version: {tag!r}")
    return tuple(int(part) for part in m.group(1).split("."))


def _project_version() -> str:
    text = PYPROJECT.read_text()
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    if not m:
        raise RuntimeError(f"{PYPROJECT}: no project version")
    return m.group(1)


def _next_version(version: str, part: str) -> str:
    parts = _version_tuple(version)
    if len(parts) != 3:
        raise RuntimeError(f"package version must be X.Y.Z, not {version!r}")
    major, minor, patch = parts
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "major":
        return f"{major + 1}.0.0"
    raise RuntimeError(f"--part must be patch, minor or major, not {part!r}")


def _pins_from_texts(ddfacet_text: str, ddfacet_mp_text: str, killms_mp_text: str, where: str) -> tuple[str, str]:
    doc = yaml.safe_load(ddfacet_text)
    try:
        ddfacet = doc["vars"]["tim-molteno"]["images"]["version"]
        killms = doc["cabs"]["killms"]["image"]["version"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"{where}/ddfacet.yml: cannot read the image pins") from exc
    ddfacet_mp = yaml.safe_load(ddfacet_mp_text)["vars"]["ddfacet-memory-plan"]["image"]["version"]
    killms_mp = yaml.safe_load(killms_mp_text)["vars"]["killms-memory-plan"]["image"]["version"]
    if ddfacet_mp != ddfacet or killms_mp != killms:
        raise RuntimeError(
            f"memory-plan pins disagree with ddfacet.yml in {where}: "
            f"ddfacet {ddfacet!r}/{ddfacet_mp!r}, killms {killms!r}/{killms_mp!r}"
        )
    return str(ddfacet), str(killms)


def _pinned_versions(base: Path | None = None) -> tuple[str, str]:
    """The DDFacet and killMS tags pinned by the cabs in `base` (default: the packaged cabs)."""
    if base is None:
        files = (DDFACET_YML, DDFACET_MP_YML, KILLMS_MP_YML)
    else:
        files = tuple(base / name for name in SYNC_FILES[:3])
    return _pins_from_texts(*(f.read_text() for f in files), where=str(base or PACKAGE_DIR))


def _committed_pins() -> tuple[str, str]:
    """The pins in the last commit (what the previous release shipped); the working tree if HEAD has none."""
    try:
        texts = [_git(ROOT, "show", f"HEAD:dde_cargo/{name}") for name in SYNC_FILES[:3]]
    except RuntimeError:
        return _pinned_versions()
    return _pins_from_texts(*texts, where="HEAD:dde_cargo")


def _release_tags(repo: Path) -> list[str]:
    raw = _git(repo, "tag", "--list", "v*", "--sort=version:refname")
    tags = [line.strip() for line in raw.splitlines() if RELEASE_TAG_RE.fullmatch(line.strip())]
    if not tags:
        raise RuntimeError(f"{repo}: no release tags (vX.Y.Z)")
    return tags


def _latest_tag(repo: Path) -> str:
    return _release_tags(repo)[-1]


def _fetch_tags(repo: Path) -> None:
    """Best-effort fetch of the upstream release tags.

    The development checkouts use SSH remotes, which can fail for reasons
    unrelated to the release (for example a system ssh_config the current user
    cannot read).  Fall back to HTTPS with gh's credential helper, then keep
    the local tags with a warning rather than making a release impossible.
    """
    try:
        _git(repo, "fetch", "--tags", "--quiet", "origin")
        return
    except RuntimeError as ssh_error:
        url = _remote_url(repo)
        if url:
            try:
                _git_https(repo, "fetch", "--tags", "--quiet", url)
                return
            except (RuntimeError, ProcessExecutionError):
                pass
        print(f"warning: could not fetch {repo}; using local tags ({ssh_error})")


def _resolve_target(repo: Path, name: str, override: str | None) -> str:
    tags = _release_tags(repo)
    if override:
        if override not in tags:
            raise RuntimeError(f"{name}: {override} is not a release tag in {repo}")
        return override
    return tags[-1]


def _commits_between(repo: Path, old: str, new: str) -> list[tuple[str, str]]:
    raw = _git(repo, "log", "--no-merges", "--reverse", "--format=%h%x09%s", f"{old}..{new}")
    commits: list[tuple[str, str]] = []
    for line in raw.splitlines():
        sha, _, subject = line.partition("\t")
        subject = subject.strip()
        if not subject or subject.startswith("release:"):
            continue
        commits.append((sha.strip(), subject))
    return commits


def _tag_date(repo: Path, tag: str) -> str:
    return _git(repo, "log", "-1", "--format=%cs", tag)


def _tag_subject(repo: Path, tag: str) -> str:
    return _git(repo, "log", "-1", "--format=%s", tag)


# ---------------------------------------------------------------------------
# syncing the cabs from meerkat_imaging


def _meerkat_cab(name: str) -> Path:
    return MEERKAT_REPO / "cabs" / name


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_meerkat() -> str:
    """Check that the cab files in meerkat_imaging are committed and current; return its HEAD commit."""
    if not (MEERKAT_REPO / ".git").exists():
        raise RuntimeError(f"meerkat_imaging repository not found at {MEERKAT_REPO} (set MEERKAT_REPO)")
    missing = [name for name in SYNC_FILES if not _meerkat_cab(name).is_file()]
    if missing:
        raise RuntimeError(f"{MEERKAT_REPO}/cabs lacks {', '.join(missing)}")
    dirty = _git(MEERKAT_REPO, "status", "--porcelain", "--", *[f"cabs/{name}" for name in SYNC_FILES])
    if dirty:
        raise RuntimeError(
            f"uncommitted cab changes in {MEERKAT_REPO}; commit them first so the recorded commit is the "
            f"synced content:\n{dirty}"
        )
    builder = MEERKAT_REPO / "tools" / "build-memplan-cabs.py"
    if builder.is_file():
        proc = subprocess.run(
            [sys.executable, str(builder), "--check"], cwd=MEERKAT_REPO, text=True, capture_output=True
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "meerkat_imaging's generated memory-plan cabs are stale "
                "(run tools/build-memplan-cabs.py there and commit):\n" + (proc.stdout + proc.stderr).strip()
            )
    return _git(MEERKAT_REPO, "rev-parse", "HEAD")


def _recorded_commit() -> str | None:
    """The meerkat_imaging commit the LAST RELEASE synced from (the record committed at HEAD)."""
    try:
        return json.loads(_git(ROOT, "show", "HEAD:dde_cargo/meerkat-sync.json"))["meerkat_imaging_commit"]
    except (RuntimeError, ValueError, KeyError):
        return None


def _sync_changed_files() -> list[str]:
    return [
        name
        for name in SYNC_FILES
        if not (PACKAGE_DIR / name).is_file()
        or (PACKAGE_DIR / name).read_bytes() != _meerkat_cab(name).read_bytes()
    ]


def _verify_sync_pins(ddfacet: str, killms: str) -> None:
    """The cabs about to be synced must pin exactly the release's DDFacet and killMS tags."""
    have = _pinned_versions(MEERKAT_REPO / "cabs")
    if have != (ddfacet, killms):
        raise RuntimeError(
            f"the cabs in {MEERKAT_REPO}/cabs pin DDFacet {have[0]} / killMS {have[1]}, but this release targets "
            f"DDFacet {ddfacet} / killMS {killms} (the latest tags of {DDFACET_REPO} / {KILLMS_REPO}).\n"
            "Refusing to publish cabs that pin other images.  Update meerkat_imaging's pins (its `invoke release` "
            "does, and commits them before calling this) or tag the matching DDFacet/killMS release first."
        )


def _update_readme_pins(ddfacet: str, killms: str) -> None:
    """Point the README's image table at the pins of the packaged cabs."""
    text = README.read_text()
    text = re.sub(r"(ghcr\.io/tmolteno/ddfacet:)v\d+(?:\.\d+)+", rf"\g<1>{ddfacet}", text)
    text = re.sub(r"(ghcr\.io/tmolteno/killms:)v\d+(?:\.\d+)+", rf"\g<1>{killms}", text)
    README.write_text(text)


def _apply_sync(commit: str) -> list[str]:
    """Copy the cab files from meerkat_imaging, record the commit, and refresh the README pins."""
    changed = _sync_changed_files()
    for name in SYNC_FILES:
        shutil.copyfile(_meerkat_cab(name), PACKAGE_DIR / name)
    SYNC_RECORD.write_text(
        json.dumps(
            {
                "meerkat_imaging_commit": commit,
                "files": {name: _sha256(PACKAGE_DIR / name) for name in SYNC_FILES},
            },
            indent=2,
        )
        + "\n"
    )
    _update_readme_pins(*_pinned_versions())
    return changed


def _cab_changes_section(old: str | None, new: str) -> list[str]:
    """A Markdown section: meerkat_imaging's commits touching the synced cab files since the last sync."""
    lines = ["### Cab changes (meerkat_imaging)", ""]
    short = new[:7]
    if old is None:
        return [*lines, f"- First sync from meerkat_imaging `{short}`; no earlier sync to compare against.", ""]
    if old == new:
        return [*lines, f"- No cab changes since the last sync (meerkat_imaging `{short}`).", ""]
    try:
        raw = _git(
            MEERKAT_REPO, "log", "--no-merges", "--reverse", "--format=%h%x09%s", f"{old}..{new}",
            "--", *[f"cabs/{name}" for name in SYNC_FILES],
        )
    except RuntimeError:
        return [*lines, f"- meerkat_imaging `{old[:7]}` → `{short}` (the history between them is not available here).", ""]
    commits = []
    for line in raw.splitlines():
        sha, _, subject = line.partition("\t")
        # pin bumps are listed under "Container images" already
        if subject.strip() and not subject.startswith("pins:"):
            commits.append(f"- {subject.strip()} (`{sha.strip()}`)")
    lines.append(f"meerkat_imaging `{old[:7]}` → `{short}`:")
    lines.append("")
    lines.extend(commits or ["- Image pin updates only."])
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# changelog generation


def _upstream_section(name: str, repo: Path, old: str, new: str) -> list[str]:
    """A Markdown section listing the upstream commits between two tags."""
    lines = [f"### {name}", ""]
    if old == new:
        return [*lines, f"- Unchanged at `{new}`.", ""]

    tags = _release_tags(repo)
    if old not in tags:
        raise RuntimeError(f"{name}: pinned tag {old} is not in {repo}")
    if new not in tags:
        raise RuntimeError(f"{name}: target tag {new} is not in {repo}")
    lo, hi = tags.index(old), tags.index(new)
    if hi <= lo:
        raise RuntimeError(f"{name}: {new} is older than the pinned {old}")

    window = tags[lo : hi + 1]
    for previous, tag in zip(window, window[1:]):
        lines.append(f"#### `{tag}` ({_tag_date(repo, tag)})")
        commits = _commits_between(repo, previous, tag)
        if commits:
            lines.extend(f"- {subject} (`{sha}`)" for sha, subject in commits)
        else:
            release_subject = _tag_subject(repo, tag)
            m = re.search(r"\bFROM ddfacet (v\d+(?:\.\d+)+)", release_subject)
            if m:
                lines.append(f"- Rebuilt on DDFacet `{m.group(1)}`; no source changes.")
            else:
                lines.append("- Release-only change (version bump).")
        lines.append("")
    return lines


def _changelog_section(
    package_old: str,
    package_new: str,
    ddfacet_old: str,
    ddfacet_new: str,
    killms_old: str,
    killms_new: str,
    meerkat_old: str | None = None,
    meerkat_new: str | None = None,
) -> str:
    lines = [
        f"## [{package_new}] - {date.today().isoformat()}",
        "",
        "### Container images",
        "",
        f"- DDFacet `ghcr.io/tmolteno/ddfacet:{ddfacet_old}` → `{ddfacet_new}`.",
        f"- killMS `ghcr.io/tmolteno/killms:{killms_old}` → `{killms_new}`.",
        "- Image pins are those of the cabs synced from meerkat_imaging, equal to the latest upstream tags.",
        "",
    ]
    lines.extend(_upstream_section("DDFacet", DDFACET_REPO, ddfacet_old, ddfacet_new))
    lines.extend(_upstream_section("killMS", KILLMS_REPO, killms_old, killms_new))
    if meerkat_new is not None:
        lines.extend(_cab_changes_section(meerkat_old, meerkat_new))
    lines.extend(
        [
            "### Packaging",
            "",
            f"- Package version bumped from `{package_old}` to `{package_new}`.",
            "- Cabs and schemas synced from `meerkat_imaging/cabs` (`invoke sync`).",
            "- Changelog generated from the `../DDFacet` and `../killMS` commit history "
            "and meerkat_imaging's cab history.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _insert_changelog(section: str, package_old: str, package_new: str) -> None:
    text = CHANGELOG.read_text()
    if f"## [{package_new}]" in text:
        raise RuntimeError(f"{CHANGELOG}: [{package_new}] is already present")

    marker = "## [Unreleased]"
    start = text.find(marker)
    if start < 0:
        raise RuntimeError(f"{CHANGELOG}: no '{marker}' heading")
    end = text.find("\n", start)
    if end < 0:
        raise RuntimeError(f"{CHANGELOG}: malformed '{marker}' heading")

    head = text[: end + 1]
    rest = text[end + 1 :]
    next_release = re.search(r"(?m)^## \[", rest)
    unreleased = (rest[: next_release.start()] if next_release else rest).strip()
    tail = rest[next_release.start() :] if next_release else ""
    if unreleased:
        section = section.rstrip() + "\n\n" + unreleased + "\n"
    text = f"{head}\n{section}\n{tail}"

    text = re.sub(
        r"(?m)^\[Unreleased\]: .*$",
        f"[Unreleased]: https://github.com/{GH_REPO}/compare/v{package_new}...HEAD",
        text,
        count=1,
    )
    previous_ref = (
        f"[{package_new}]: https://github.com/{GH_REPO}/compare/"
        f"v{package_old}...v{package_new}"
    )
    if re.search(r"(?m)^\[Unreleased\]: ", text):
        text = re.sub(
            r"(?m)^(\[Unreleased\]: .*)$",
            lambda m: f"{m.group(1)}\n{previous_ref}",
            text,
            count=1,
        )
    else:
        # a minimal changelog may have no link-reference block at all
        text = (
            text.rstrip()
            + f"\n\n[Unreleased]: https://github.com/{GH_REPO}/compare/v{package_new}...HEAD"
            + f"\n{previous_ref}\n"
        )
    CHANGELOG.write_text(text)


def _changelog_entry(version: str) -> str:
    """The final `## [version]` section, including any Unreleased notes."""
    text = CHANGELOG.read_text()
    match = re.search(
        rf"(?ms)^## \[{re.escape(version)}\].*?(?=^## \[|^\[[^\]]+\]: |\Z)", text
    )
    if not match:
        raise RuntimeError(f"{CHANGELOG}: no section for [{version}]")
    return match.group(0).strip()


# ---------------------------------------------------------------------------
# applying the release


def _set_project_version(version: str) -> None:
    text, count = re.subn(
        r'(?m)^(version\s*=\s*")[^"]+(")',
        rf"\g<1>{version}\g<2>",
        PYPROJECT.read_text(),
        count=1,
    )
    if count != 1:
        raise RuntimeError(f"{PYPROJECT}: no version line")
    PYPROJECT.write_text(text)


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one {old!r}, found {count}")
    path.write_text(text.replace(old, new, 1))


def _verify_pins(ddfacet: str, killms: str) -> None:
    actual = _pinned_versions()
    if actual != (ddfacet, killms):
        raise RuntimeError(f"pin check failed: expected {(ddfacet, killms)}, found {actual}")
    readme = README.read_text()
    for image, tag in (("ddfacet", ddfacet), ("killms", killms)):
        if f"ghcr.io/tmolteno/{image}:{tag}" not in readme:
            raise RuntimeError(f"{README}: no {image} {tag} in the image table")


def _pypi_has_version(version: str) -> bool:
    url = "https://pypi.org/pypi/dde-cargo/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise RuntimeError(f"PyPI lookup failed: {exc}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"PyPI lookup failed: {exc}") from exc
    return version in data.get("releases", {})


def _remote_tag_exists(tag: str) -> bool:
    try:
        out = _git_https(ROOT, "ls-remote", "--tags", REMOTE_URL, f"refs/tags/{tag}")
    except ProcessExecutionError as exc:
        raise RuntimeError(f"cannot read {REMOTE_URL}: {exc}") from exc
    return bool(out.strip())


def _local_tag_exists(tag: str) -> bool:
    rc, _, _ = local["git"][
        ("-C", str(ROOT), "rev-parse", "--verify", "-q", f"refs/tags/{tag}")
    ].run(retcode=None)
    return rc == 0


def _wait_for_publish(tag: str, commit: str, timeout_s: int = 900) -> None:
    """Wait for the tag's Publish dde-cargo workflow run to succeed."""
    start = time.time()
    run_id: int | None = None
    while run_id is None:
        raw = _run(
            "gh", "run", "list", "--repo", GH_REPO, "-w", WORKFLOW, "--limit", "20",
            "--json", "databaseId,headBranch,headSha,status,conclusion",
        )
        runs = json.loads(raw)
        mine = [r for r in runs if r["headBranch"] == tag and r["headSha"] == commit]
        if mine:
            run_id = mine[0]["databaseId"]
            break
        if time.time() - start > timeout_s:
            raise RuntimeError(f"no {WORKFLOW} run appeared for {tag} within {timeout_s}s")
        print(f"  waiting for the {tag} publish run to register...")
        time.sleep(10)

    while True:
        raw = _run(
            "gh", "run", "view", str(run_id), "--repo", GH_REPO,
            "--json", "status,conclusion",
        )
        data = json.loads(raw)
        status, conclusion = data.get("status"), data.get("conclusion")
        if status == "completed":
            if conclusion == "success":
                print(f"  publish workflow {run_id}: success")
                return
            raise RuntimeError(
                f"publish workflow {run_id} ended {conclusion}; "
                f"see: gh run view {run_id} --repo {GH_REPO} --log-failed"
            )
        print(f"  publish workflow {run_id}: {status}")
        if time.time() - start > timeout_s:
            raise RuntimeError(f"publish workflow {run_id} timed out after {timeout_s}s")
        time.sleep(10)


def _wait_for_pypi(version: str, timeout_s: int = 300) -> None:
    start = time.time()
    while time.time() - start < timeout_s:
        if _pypi_has_version(version):
            print(f"  PyPI: dde-cargo {version} is live")
            return
        time.sleep(5)
    raise RuntimeError(f"PyPI did not expose dde-cargo {version} within {timeout_s}s")


def _release_notes(section: str, version: str) -> str:
    return (
        "Stimela 2 cabs for DDFacet and killMS on amd64 and arm64.\n\n"
        f"This release tracks the upstream `../DDFacet` and `../killMS` tags.\n\n"
        f"{section}\n"
        "## Install\n\n"
        "```sh\n"
        f"pip install dde-cargo=={version}\n"
        "```\n\n"
        f"**Full changelog:** https://github.com/{GH_REPO}/blob/main/CHANGELOG.md\n"
    )


# ---------------------------------------------------------------------------
# planning and preflight


def _plan(
    part: str = "patch",
    ddfacet_tag: str | None = None,
    killms_tag: str | None = None,
    allow_same: bool = False,
    fetch: bool = True,
    check_pypi: bool = False,
) -> dict[str, str]:
    for repo, name in ((DDFACET_REPO, "DDFacet"), (KILLMS_REPO, "killMS")):
        if not (repo / ".git").exists():
            raise RuntimeError(f"{name} repository not found at {repo}")
        if fetch:
            _fetch_tags(repo)

    package_old = _project_version()
    package_new = _next_version(package_old, part)
    # "old" is what the last release shipped (the committed cabs), so a sync already applied to the working
    # tree does not hide the changes; "new" must be what meerkat_imaging's cabs pin.
    ddfacet_old, killms_old = _committed_pins()
    ddfacet_new = _resolve_target(DDFACET_REPO, "DDFacet", ddfacet_tag)
    killms_new = _resolve_target(KILLMS_REPO, "killMS", killms_tag)
    meerkat_new = _require_meerkat()
    meerkat_old = _recorded_commit()
    _verify_sync_pins(ddfacet_new, killms_new)
    cabs_changed = _sync_changed_files()

    if _version_tuple(ddfacet_new) < _version_tuple(ddfacet_old):
        raise RuntimeError(f"DDFacet target {ddfacet_new} is older than the pin {ddfacet_old}")
    if _version_tuple(killms_new) < _version_tuple(killms_old):
        raise RuntimeError(f"killMS target {killms_new} is older than the pin {killms_old}")
    cab_commits = meerkat_old != meerkat_new
    if ddfacet_new == ddfacet_old and killms_new == killms_old and not allow_same and not (cabs_changed or cab_commits):
        raise RuntimeError(
            "DDFacet and killMS are at the pinned tags and the cabs in meerkat_imaging are already released "
            f"(commit {str(meerkat_old)[:7]}); pass --allow-same to release packaging changes only"
        )
    if check_pypi and _pypi_has_version(package_new):
        raise RuntimeError(f"dde-cargo {package_new} is already on PyPI; bump again")

    section = _changelog_section(
        package_old, package_new, ddfacet_old, ddfacet_new, killms_old, killms_new, meerkat_old, meerkat_new
    )
    return {
        "package_old": package_old,
        "package_new": package_new,
        "ddfacet_old": ddfacet_old,
        "ddfacet_new": ddfacet_new,
        "killms_old": killms_old,
        "killms_new": killms_new,
        "meerkat_old": meerkat_old or "",
        "meerkat_new": meerkat_new,
        "cabs_changed": ", ".join(cabs_changed) or "(none)",
        "section": section,
    }


def _preflight(require_clean: bool, require_gh: bool = False) -> None:
    _require_tools("git", "uv")
    if require_gh:
        _require_tools("gh")
        _run("gh", "auth", "status")
    branch = _git(ROOT, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        if require_clean:  # a real release; a dry run changes nothing, so any branch may show its plan
            raise RuntimeError(f"release from main, not {branch!r}")
        print(f"note: on branch {branch!r}; a real release must run from main")
    if require_clean:
        dirty = _git(ROOT, "status", "--porcelain")
        if dirty:
            raise RuntimeError(f"working tree is not clean:\n{dirty}")


def _print_plan(plan: dict[str, str]) -> None:
    print(
        f"dde-cargo {plan['package_old']} -> {plan['package_new']}\n"
        f"DDFacet    {plan['ddfacet_old']} -> {plan['ddfacet_new']}\n"
        f"killMS     {plan['killms_old']} -> {plan['killms_new']}\n"
        f"meerkat_imaging cabs {plan['meerkat_old'][:7] or '(first sync)'} -> {plan['meerkat_new'][:7]}"
        f" (files that differ from dde_cargo/: {plan['cabs_changed']})\n"
    )


# ---------------------------------------------------------------------------
# invoke tasks


@task
def version(c) -> None:
    """Show this package's version, its pins, and the latest upstream tags."""
    print(f"dde-cargo: {_project_version()}")
    ddfacet, killms = _pinned_versions()
    ddfacet_latest = _latest_tag(DDFACET_REPO)
    killms_latest = _latest_tag(KILLMS_REPO)
    recorded = _recorded_commit()
    print(f"meerkat_imaging cabs: synced at {(recorded or 'none')[:7]}, "
          f"{MEERKAT_REPO} is at {_git(MEERKAT_REPO, 'rev-parse', '--short', 'HEAD')}")
    print(f"DDFacet:   pinned {ddfacet}, latest {ddfacet_latest}")
    print(f"killMS:    pinned {killms}, latest {killms_latest}")
    if (ddfacet, killms) == (ddfacet_latest, killms_latest):
        print("both images are already at the pinned tags (use --allow-same to release packaging only)")
    else:
        print(f"next release targets DDFacet {ddfacet_latest} and killMS {killms_latest}")


@task(
    help={
        "check": "report (exit 1) when dde_cargo/ differs from meerkat_imaging, copy nothing",
    }
)
def sync(c, check: bool = False) -> None:
    """Copy the five cab files from meerkat_imaging/cabs into dde_cargo/ and record the commit.

    The cabs are edited in meerkat_imaging (MEERKAT_REPO, default ../meerkat_imaging), never here.  Refuses
    when those files are uncommitted there.  `release` runs this first; run `invoke docs` after a sync
    (the release does).
    """
    try:
        commit = _require_meerkat()
        changed = _sync_changed_files()
        if check:
            if changed:
                print(f"dde_cargo/ differs from {MEERKAT_REPO}/cabs: {', '.join(changed)}")
                raise SystemExit(1)
            print(f"dde_cargo/ matches meerkat_imaging {commit[:7]}")
            return
        _apply_sync(commit)
        print(f"synced from meerkat_imaging {commit[:7]} ({MEERKAT_REPO})")
        print(f"changed: {', '.join(changed) or '(nothing: already identical)'}")
        ddfacet, killms = _pinned_versions()
        print(f"pins now: DDFacet {ddfacet}, killMS {killms}")
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


@task(
    help={
        "check": "verify docs/cabs.md is current without writing it",
    }
)
def docs(c, check: bool = False) -> None:
    """Regenerate the cab reference from the packaged YAMLs."""
    argv = ["uv", "run", "python", "tools/gen_cab_docs.py"]
    if check:
        argv.append("--check")
    try:
        _run(*argv, stream=True)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


@task(
    help={
        "part": "version part to bump: patch (default), minor or major",
        "ddfacet_tag": "override the DDFacet target tag (default: latest)",
        "killms_tag": "override the killMS target tag (default: latest)",
        "allow_same": "generate notes even when both images are already at the pins",
        "fetch": "fetch upstream tags first (default: true)",
    }
)
def changelog(
    c,
    part: str = "patch",
    ddfacet_tag: str | None = None,
    killms_tag: str | None = None,
    allow_same: bool = False,
    fetch: bool = True,
) -> None:
    """Print the changelog section the next release would generate."""
    plan = _plan(part, ddfacet_tag, killms_tag, allow_same, fetch)
    _print_plan(plan)
    print(plan["section"])


@task(
    help={
        "part": "version part to bump: patch (default), minor (a cab interface changed) or major",
        "ddfacet_tag": "override the DDFacet target tag (default: latest)",
        "killms_tag": "override the killMS target tag (default: latest)",
        "allow_same": "release even when nothing (pins, cabs) changed since the last release",
        "fetch": "fetch upstream tags first (default: true)",
        "yes": "do not ask for confirmation",
        "dry_run": "print the plan and changelog, change nothing",
    }
)
def release(
    c,
    part: str = "patch",
    ddfacet_tag: str | None = None,
    killms_tag: str | None = None,
    allow_same: bool = False,
    fetch: bool = True,
    yes: bool = False,
    dry_run: bool = False,
) -> None:
    """Sync the cabs, bump, changelog, test, tag, publish to PyPI and create the GitHub release."""
    try:
        _preflight(require_clean=not dry_run, require_gh=not dry_run)
        plan = _plan(part, ddfacet_tag, killms_tag, allow_same, fetch, check_pypi=not dry_run)
        _print_plan(plan)
        print(plan["section"])

        if dry_run:
            print("dry run: no files changed, nothing committed or published")
            return

        _require_tools("gh")
        tag = f"v{plan['package_new']}"
        if _local_tag_exists(tag) or _remote_tag_exists(tag):
            raise RuntimeError(f"{tag} already exists (local or on {REMOTE_URL})")

        if not yes:
            print(f"About to release dde-cargo {plan['package_new']} as {tag}.")
            print("This commits, tags, pushes, publishes to PyPI and creates a GitHub release.")
            try:
                answer = input("Proceed? [y/N] ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in {"y", "yes"}:
                raise SystemExit("aborted")

        print(f"=== syncing the cabs from meerkat_imaging {plan['meerkat_new'][:7]}")
        _apply_sync(plan["meerkat_new"])
        print("=== updating version and changelog")
        _set_project_version(plan["package_new"])
        _insert_changelog(plan["section"], plan["package_old"], plan["package_new"])
        _verify_pins(plan["ddfacet_new"], plan["killms_new"])
        notes_section = _changelog_entry(plan["package_new"])

        print("=== regenerating docs/cabs.md")
        _run("uv", "run", "python", "tools/gen_cab_docs.py", stream=True)

        print("=== refreshing uv.lock")
        _run("uv", "lock", "--quiet")

        print("=== running tests")
        _run("uv", "run", "pytest", "-q")

        with tempfile.TemporaryDirectory(prefix="dde-cargo-release-") as tmp:
            artifacts_dir = Path(tmp) / "dist"
            print("=== building wheel and sdist")
            _run("uv", "build", "--out-dir", str(artifacts_dir))
            artifacts = sorted(artifacts_dir.glob("dde_cargo-*.whl")) + sorted(
                artifacts_dir.glob("dde_cargo-*.tar.gz")
            )
            if len(artifacts) != 2:
                raise RuntimeError(f"expected a wheel and an sdist, found {artifacts}")

            message = (
                f"dde-cargo {plan['package_new']}: "
                f"DDFacet {plan['ddfacet_new']}, killMS {plan['killms_new']}"
            )
            print(f"=== committing {message}")
            _run("git", "add", "-A")
            _run("git", "commit", "-m", message, "-m",
                 f"Sync the cabs from meerkat_imaging {plan['meerkat_new'][:7]} and generate the "
                 "changelog from the upstream DDFacet and killMS histories and the cab history.")
            _run("git", "tag", "-a", tag, "-m", message)
            commit = _git(ROOT, "rev-parse", "HEAD")

            print(f"=== pushing main and {tag} (this triggers the PyPI workflow)")
            _run(
                "git", "-c", CREDENTIAL_HELPER,
                "push", REMOTE_URL, "main", tag,
                stream=True,
            )
            _wait_for_publish(tag, commit)
            _wait_for_pypi(plan["package_new"])

            notes_path = Path(tmp) / "release-notes.md"
            notes_path.write_text(_release_notes(notes_section, plan["package_new"]))
            print(f"=== creating GitHub release {tag}")
            _run(
                "gh", "release", "create", "--repo", GH_REPO, tag,
                "--verify-tag", "--latest", "--title", f"dde-cargo {plan['package_new']}",
                "--notes-file", str(notes_path), *[str(path) for path in artifacts],
                stream=True,
            )
        print(f"\n=== RELEASE COMPLETE: dde-cargo {plan['package_new']}")
    except (RuntimeError, ProcessExecutionError) as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
