# Copyright (c) 2026 Tim Molteno (tim@elec.ac.nz)
"""Tests for the invoke/plumbum release automation in tasks.py.

These tests exercise the pure planning and rewriting helpers only; the
upstream repositories and GitHub are mocked or replaced with temporary files.
"""

import json
from pathlib import Path

import pytest

import tasks


def test_version_bumps():
    assert tasks._next_version("0.1.1", "patch") == "0.1.2"
    assert tasks._next_version("0.1.1", "minor") == "0.2.0"
    assert tasks._next_version("0.1.1", "major") == "1.0.0"
    assert tasks._version_tuple("v0.16.6") == (0, 16, 6)
    assert tasks._version_tuple("v0.16.6.1") == (0, 16, 6, 1)


def test_insert_changelog_carries_unreleased_notes(tmp_path, monkeypatch):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Added\n\n- pending change\n\n"
        "## [0.1.0] - 2026-01-01\n\n### Added\n\n- initial\n"
    )
    monkeypatch.setattr(tasks, "CHANGELOG", changelog)
    monkeypatch.setattr(tasks, "GH_REPO", "owner/repo")

    section = "## [0.1.1] - 2026-01-02\n\n### Packaging\n\n- generated\n"
    tasks._insert_changelog(section, "0.1.0", "0.1.1")

    text = changelog.read_text()
    assert "## [Unreleased]\n\n## [0.1.1]" in text
    assert "- pending change" in text
    assert (
        "[Unreleased]: https://github.com/owner/repo/compare/v0.1.1...HEAD"
        in text
    )
    assert (
        "[0.1.1]: https://github.com/owner/repo/compare/v0.1.0...v0.1.1"
        in text
    )
    entry = tasks._changelog_entry("0.1.1")
    assert "- generated" in entry and "- pending change" in entry


def test_upstream_section_lists_commits_and_rebuilds(monkeypatch):
    monkeypatch.setattr(
        tasks, "_release_tags", lambda repo: ["v1.0.0", "v1.1.0", "v1.2.0"]
    )
    monkeypatch.setattr(tasks, "_tag_date", lambda repo, tag: "2026-01-01")

    def commits(repo, old, new):
        return {
            "v1.0.0..v1.1.0": [("abc123", "Fix one")],
            "v1.1.0..v1.2.0": [],
        }[f"{old}..{new}"]

    monkeypatch.setattr(tasks, "_commits_between", commits)
    monkeypatch.setattr(
        tasks,
        "_tag_subject",
        lambda repo, tag: (
            "release: v1.2.0 -- FROM ddfacet v1.0.0" if tag == "v1.2.0" else "release"
        ),
    )

    text = "\n".join(
        tasks._upstream_section("DDFacet", Path("/tmp/DDFacet"), "v1.0.0", "v1.2.0")
    )
    assert "#### `v1.1.0` (2026-01-01)" in text
    assert "- Fix one (`abc123`)" in text
    assert "- Rebuilt on DDFacet `v1.0.0`; no source changes." in text


def _write_cabs(directory, ddfacet, killms):
    directory.mkdir(exist_ok=True)
    (directory / "ddfacet.yml").write_text(
        "vars:\n  tim-molteno:\n    images:\n      version: %s\n"
        "cabs:\n  killms:\n    image:\n      version: %s\n" % (ddfacet, killms)
    )
    (directory / "ddfacet-memory-plan.yml").write_text(
        "vars:\n  ddfacet-memory-plan:\n    image:\n      version: %s\n" % ddfacet
    )
    (directory / "killms-memory-plan.yml").write_text(
        "vars:\n  killms-memory-plan:\n    image:\n      version: %s\n" % killms
    )
    for name in tasks.SYNC_FILES[3:]:
        (directory / name).write_text("# schema\n")


def _git_init(path):
    import subprocess

    for argv in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(path), *argv], check=True)


def _commit(path, message):
    import subprocess

    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", message], check=True)
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _fake_world(tmp_path, monkeypatch, meerkat_pins=("v0.16.2", "v3.15.4")):
    """A tiny dde-cargo repo (pins v0.16.1/v3.15.3, released) and a meerkat_imaging repo beside it."""
    mine, meerkat = tmp_path / "dde-cargo", tmp_path / "meerkat_imaging"
    pkg = mine / "dde_cargo"
    mine.mkdir()
    meerkat.mkdir()
    _git_init(mine)
    _git_init(meerkat)
    _write_cabs(pkg, "v0.16.1", "v3.15.3")
    (mine / "README.md").write_text(
        "| ddfacet | ghcr.io/tmolteno/ddfacet:v0.16.1 |\n| killms | ghcr.io/tmolteno/killms:v3.15.3 |\n"
    )
    _write_cabs(meerkat / "cabs", "v0.16.1", "v3.15.3")
    first = _commit(meerkat, "initial cabs")
    monkeypatch.setattr(tasks, "ROOT", mine)
    monkeypatch.setattr(tasks, "PACKAGE_DIR", pkg)
    monkeypatch.setattr(tasks, "SYNC_RECORD", pkg / "meerkat-sync.json")
    monkeypatch.setattr(tasks, "MEERKAT_REPO", meerkat)
    monkeypatch.setattr(tasks, "README", mine / "README.md")
    monkeypatch.setattr(tasks, "DDFACET_YML", pkg / "ddfacet.yml")
    monkeypatch.setattr(tasks, "DDFACET_MP_YML", pkg / "ddfacet-memory-plan.yml")
    monkeypatch.setattr(tasks, "KILLMS_MP_YML", pkg / "killms-memory-plan.yml")
    tasks._apply_sync(first)
    _commit(mine, "release 0.1.0")  # the committed record is the previous release's sync
    _write_cabs(meerkat / "cabs", *meerkat_pins)
    (meerkat / "cabs" / "killms-memory-plan.yml").write_text(
        (meerkat / "cabs" / "killms-memory-plan.yml").read_text() + "# a planner change\n"
    )
    second = _commit(meerkat, "memplan: calibrated planner")
    return mine, meerkat, first, second


def test_sync_copies_cabs_records_commit_and_updates_readme(tmp_path, monkeypatch):
    mine, meerkat, first, second = _fake_world(tmp_path, monkeypatch)
    assert tasks._recorded_commit() == first
    assert tasks._require_meerkat() == second
    assert "killms-memory-plan.yml" in tasks._sync_changed_files()

    changed = tasks._apply_sync(second)

    assert "ddfacet.yml" in changed
    assert tasks._pinned_versions() == ("v0.16.2", "v3.15.4")
    record = json.loads((mine / "dde_cargo" / "meerkat-sync.json").read_text())
    assert record["meerkat_imaging_commit"] == second
    assert record["files"]["ddfacet.yml"] == tasks._sha256(mine / "dde_cargo" / "ddfacet.yml")
    readme = (mine / "README.md").read_text()
    assert "ddfacet:v0.16.2" in readme and "killms:v3.15.4" in readme and "v0.16.1" not in readme
    tasks._verify_pins("v0.16.2", "v3.15.4")
    assert tasks._sync_changed_files() == []
    # the committed pins (what the last release shipped) are still the old ones
    assert tasks._committed_pins() == ("v0.16.1", "v3.15.3")


def test_sync_refuses_uncommitted_cab_changes(tmp_path, monkeypatch):
    mine, meerkat, first, second = _fake_world(tmp_path, monkeypatch)
    (meerkat / "cabs" / "ddfacet.yml").write_text("# edited, not committed\n")
    with pytest.raises(RuntimeError, match="uncommitted cab changes"):
        tasks._require_meerkat()


def test_release_refuses_cabs_that_pin_other_images(tmp_path, monkeypatch):
    _fake_world(tmp_path, monkeypatch)
    tasks._verify_sync_pins("v0.16.2", "v3.15.4")  # the meerkat cabs pin exactly these
    with pytest.raises(RuntimeError, match="Refusing to publish cabs that pin other images"):
        tasks._verify_sync_pins("v0.16.3", "v3.15.4")
    with pytest.raises(RuntimeError, match="killMS v3.15.4"):
        tasks._verify_sync_pins("v0.16.2", "v3.15.5")


def test_cab_changes_section_lists_meerkat_cab_commits(tmp_path, monkeypatch):
    mine, meerkat, first, second = _fake_world(tmp_path, monkeypatch)
    text = "\n".join(tasks._cab_changes_section(first, second))
    assert "### Cab changes (meerkat_imaging)" in text
    assert "memplan: calibrated planner" in text and second[:7] in text
    assert "First sync" in "\n".join(tasks._cab_changes_section(None, second))
    assert "No cab changes" in "\n".join(tasks._cab_changes_section(second, second))


def test_plan_includes_cab_changes_and_verifies_pins(tmp_path, monkeypatch):
    mine, meerkat, first, second = _fake_world(tmp_path, monkeypatch)
    monkeypatch.setattr(tasks, "_fetch_tags", lambda repo: None)
    monkeypatch.setattr(tasks, "DDFACET_REPO", tmp_path / "ddf")
    monkeypatch.setattr(tasks, "KILLMS_REPO", tmp_path / "kms")
    (tmp_path / "ddf" / ".git").mkdir(parents=True)
    (tmp_path / "kms" / ".git").mkdir(parents=True)
    (mine / "pyproject.toml").write_text('[project]\nversion = "0.1.1"\n')
    monkeypatch.setattr(tasks, "PYPROJECT", mine / "pyproject.toml")
    monkeypatch.setattr(tasks, "_release_tags", lambda repo: ["v0.16.1", "v0.16.2"] if repo.name == "ddf" else ["v3.15.3", "v3.15.4"])
    monkeypatch.setattr(tasks, "_tag_date", lambda repo, tag: "2026-01-01")
    monkeypatch.setattr(tasks, "_commits_between", lambda repo, old, new: [("abc", "upstream fix")])

    plan = tasks._plan("minor", fetch=False)

    assert plan["package_new"] == "0.2.0"
    assert (plan["ddfacet_old"], plan["ddfacet_new"]) == ("v0.16.1", "v0.16.2")
    assert plan["meerkat_old"] == first and plan["meerkat_new"] == second
    assert "memplan: calibrated planner" in plan["section"]
    assert "upstream fix" in plan["section"]

    # an upstream tag that the synced cabs do not pin is refused
    monkeypatch.setattr(tasks, "_release_tags", lambda repo: ["v0.16.1", "v0.16.2", "v0.16.3"] if repo.name == "ddf" else ["v3.15.3", "v3.15.4"])
    with pytest.raises(RuntimeError, match="pin DDFacet v0.16.2"):
        tasks._plan("minor", fetch=False)
