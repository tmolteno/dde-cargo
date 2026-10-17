# Copyright (c) 2026 Tim Molteno (tim@elec.ac.nz)
"""Contracts for the generated cab reference in docs/cabs.md."""

import re
import subprocess
import sys
from pathlib import Path

import yaml
from scabha.cargo import Cargo

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "cabs.md"
CAB_FILES = (
    ROOT / "dde_cargo" / "ddfacet.yml",
    ROOT / "dde_cargo" / "ddfacet-memory-plan.yml",
    ROOT / "dde_cargo" / "killms-memory-plan.yml",
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _cabs() -> dict[str, dict]:
    cabs = {}
    for path in CAB_FILES:
        doc = yaml.safe_load(path.read_text())
        for name, cab in doc["cabs"].items():
            cabs[name] = {"cab": cab, "path": path, "doc": doc}
    return cabs


def _flatten(mapping: dict) -> dict:
    flat = {}
    Cargo.flatten_schemas(flat, mapping, label="test")
    return flat


def _merged_inputs(cab: dict, path: Path) -> dict:
    raw = cab.get("inputs") or {}
    merged = {}
    include = raw.get("_include")
    for name in include if isinstance(include, list) else ([include] if include else []):
        merged.update(yaml.safe_load((path.parent / name).read_text()))
    merged.update({key: value for key, value in raw.items() if key != "_include"})
    return merged


def test_docs_are_current():
    result = subprocess.run(
        [sys.executable, "tools/gen_cab_docs.py", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_cab_has_a_section_and_table_row():
    text = DOCS.read_text()
    for name in _cabs():
        assert f'<a id="cab-{_slug(name)}"></a>' in text, name
        assert f"[`{name}`](#cab-{_slug(name)})" in text, name


def test_every_parameter_and_output_is_documented():
    text = DOCS.read_text()
    for name, info in _cabs().items():
        inputs = _flatten(_merged_inputs(info["cab"], info["path"]))
        outputs = _flatten(info["cab"].get("outputs") or {})
        for parameter in list(inputs) + list(outputs):
            assert f"`{parameter}`" in text, f"{name}: {parameter} is missing from docs"


def test_current_image_pins_and_include_order_are_documented():
    text = DOCS.read_text()
    ddfacet = yaml.safe_load(CAB_FILES[0].read_text())
    pins = (
        ddfacet["vars"]["tim-molteno"]["images"]["version"],
        ddfacet["cabs"]["killms"]["image"]["version"],
    )
    assert f"ghcr.io/tmolteno/ddfacet:{pins[0]}" in text
    assert f"ghcr.io/tmolteno/killms:{pins[1]}" in text
    assert "cultcargo" in text and "bdsf.yml" in text
