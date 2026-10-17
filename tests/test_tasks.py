# Copyright (c) 2026 Tim Molteno (tim@elec.ac.nz)
"""Tests for the invoke/plumbum release automation in tasks.py.

These tests exercise the pure planning and rewriting helpers only; the
upstream repositories and GitHub are mocked or replaced with temporary files.
"""

from pathlib import Path

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


def test_update_pins_rewrites_cabs_and_readme(tmp_path, monkeypatch):
    cabs = tmp_path / "dde_cargo"
    cabs.mkdir()
    ddfacet = cabs / "ddfacet.yml"
    ddfacet.write_text(
        "vars:\n"
        "  tim-molteno:\n"
        "    images:\n"
        "      version: v0.16.1\n"
        "cabs:\n"
        "  killms:\n"
        "    image:\n"
        "      version: v3.15.3\n"
    )
    ddfacet_mp = cabs / "ddfacet-memory-plan.yml"
    ddfacet_mp.write_text(
        "vars:\n  ddfacet-memory-plan:\n    image:\n      version: v0.16.1\n"
    )
    killms_mp = cabs / "killms-memory-plan.yml"
    killms_mp.write_text(
        "vars:\n  killms-memory-plan:\n    image:\n      version: v3.15.3\n"
    )
    readme = tmp_path / "README.md"
    readme.write_text(
        "| ddfacet | ghcr.io/tmolteno/ddfacet:v0.16.1 |\n"
        "| killms | ghcr.io/tmolteno/killms:v3.15.3 |\n"
    )

    monkeypatch.setattr(tasks, "DDFACET_YML", ddfacet)
    monkeypatch.setattr(tasks, "DDFACET_MP_YML", ddfacet_mp)
    monkeypatch.setattr(tasks, "KILLMS_MP_YML", killms_mp)
    monkeypatch.setattr(tasks, "README", readme)

    tasks._update_pins("v0.16.1", "v0.16.2", "v3.15.3", "v3.15.4")
    tasks._verify_pins("v0.16.2", "v3.15.4")

    assert tasks._pinned_versions() == ("v0.16.2", "v3.15.4")
    assert "v0.16.1" not in readme.read_text()
    assert "v3.15.3" not in readme.read_text()
