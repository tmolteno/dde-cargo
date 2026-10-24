# Copyright (c) 2026 Tim Molteno (tim@elec.ac.nz)
"""Contracts for the cabs synced from meerkat_imaging (`invoke sync`)."""

import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "dde_cargo"
SYNC_FILES = (
    "ddfacet.yml",
    "ddfacet-memory-plan.yml",
    "killms-memory-plan.yml",
    "ddfacet_stimela_inputs_schema.yml",
    "killms_stimela_schema.yml",
    "pick-reference-ant.yml",
)
MEMORY_PLAN_CABS = {
    "ddfacet-memory-plan.yml": "ddfacet-memory-plan",
    "killms-memory-plan.yml": "killms-memory-plan",
}


def test_packaged_cabs_are_the_synced_files():
    """dde_cargo/ is never edited by hand: its files are what `invoke sync` recorded."""
    record = json.loads((PACKAGE / "meerkat-sync.json").read_text())
    assert len(record["meerkat_imaging_commit"]) == 40
    assert set(record["files"]) == set(SYNC_FILES)
    for name, digest in record["files"].items():
        assert hashlib.sha256((PACKAGE / name).read_bytes()).hexdigest() == digest, (
            f"{name} differs from the synced copy: edit it in meerkat_imaging/cabs and run `invoke sync`"
        )


def test_memory_plan_cabs_reference_no_host_files():
    """The cab code runs inside the DDFacet/killMS container, where dde_cargo is not installed and the
    meerkat_imaging checkout does not exist: the planner code and model must travel inside the cab."""
    for filename, cab_name in MEMORY_PLAN_CABS.items():
        cab = yaml.safe_load((PACKAGE / filename).read_text())["cabs"][cab_name]
        inputs = cab["inputs"]
        assert "Lib" not in inputs and "ModelFile" not in inputs, cab_name
        for name, spec in inputs.items():
            default = spec.get("default") if isinstance(spec, dict) else None
            if spec.get("dtype") == "File" and isinstance(default, str) and name != "PlanOut":
                raise AssertionError(f"{cab_name}.{name} is a File input defaulting to host path {default!r}")
        command = cab["command"]
        assert "spec_from_file_location" not in command
        compile(command, cab_name, "exec")


def test_memory_plan_cabs_pin_the_image_pins_of_ddfacet_yml():
    ddfacet = yaml.safe_load((PACKAGE / "ddfacet.yml").read_text())
    pins = (
        ddfacet["vars"]["tim-molteno"]["images"]["version"],
        ddfacet["cabs"]["killms"]["image"]["version"],
    )
    got = (
        yaml.safe_load((PACKAGE / "ddfacet-memory-plan.yml").read_text())["vars"]["ddfacet-memory-plan"]["image"]["version"],
        yaml.safe_load((PACKAGE / "killms-memory-plan.yml").read_text())["vars"]["killms-memory-plan"]["image"]["version"],
    )
    assert got == pins


def test_pick_reference_ant_runs_on_the_ddfacet_pin():
    """pick-reference-ant.yml carries no vars of its own: its image `_use`s
    ddfacet.yml's vars.tim-molteno.images, so a recipe must include it after
    ddfacet.yml and it always runs on the packaged DDFacet pin (unlike the
    memory-plan cabs, which define their own vars to stay standalone)."""
    doc = yaml.safe_load((PACKAGE / "pick-reference-ant.yml").read_text())
    assert set(doc.get("cabs") or {}) == {"pick-reference-ant"}
    assert "vars" not in doc
    cab = doc["cabs"]["pick-reference-ant"]
    assert cab["image"] == {"_use": "vars.tim-molteno.images", "name": "tmolteno/ddfacet"}
    # stimela refuses a cab whose name is both an input and an output
    assert not set(cab.get("inputs") or {}) & set(cab.get("outputs") or {})
