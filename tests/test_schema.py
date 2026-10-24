# Copyright (c) 2026 Tim Molteno (tim@elec.ac.nz)
"""Schema contracts for the packaged DDFacet/killMS stimela cabs.

The cab YAMLs are copied verbatim from meerkat_imaging/cabs, so these tests
pin the properties a recipe depends on (cab inventory, merged schema inputs,
image pins, stimela's hard declarations rules) rather than the parameter
details -- a verbatim re-copy from upstream should pass unchanged unless the
contracts themselves moved.

PyYAML is used instead of OmegaConf so the dotted cab name `bdsf.catalog`
stays a single flat key.
"""

import pytest
import yaml
from importlib import resources
from pathlib import Path

PACKAGE = "dde_cargo"

CABS_FILE = "ddfacet.yml"
DDFACET_SCHEMA_FILE = "ddfacet_stimela_inputs_schema.yml"
KILLMS_SCHEMA_FILE = "killms_stimela_schema.yml"
DDFACET_MEMORY_PLAN_FILE = "ddfacet-memory-plan.yml"
KILLMS_MEMORY_PLAN_FILE = "killms-memory-plan.yml"

EXPECTED_CABS = {
    "bdsf.catalog",
    "ddfacet",
    "killms",
    "ddf_makemodel",
    "ddf_makemask",
    "dilatemask",
    "clustercat",
    "ddfacet-get-npix",
    "modelcat",
    "autofacet",
    "snapnodes",
}

EXPECTED_IMAGE_PREFIXES = {
    "killms": "ghcr.io/tmolteno/killms",
}
DEFAULT_IMAGE_PREFIX = "ghcr.io/tmolteno/ddfacet"


def _load(name):
    return yaml.safe_load(resources.files(PACKAGE).joinpath(name).read_text())


def _package_file(name) -> Path:
    return resources.files(PACKAGE).joinpath(name)


@pytest.fixture(scope="module")
def cabs_doc():
    return _load(CABS_FILE)


@pytest.fixture(scope="module")
def cabs(cabs_doc):
    return cabs_doc["cabs"]


def _merged_inputs(cab, cabs_doc):
    """A cab's inputs with its `_include`d schema merged in (stimela resolves
    the include against the file's own directory; the schema parameters are
    what a recipe actually binds)."""
    inputs = {k: v for k, v in (cab.get("inputs") or {}).items() if k != "_include"}
    include = (cab.get("inputs") or {}).get("_include")
    if include:
        schema = _load(include)
        for key, value in schema.items():
            assert key not in inputs, f"schema key '{key}' collides with a direct input"
            inputs[key] = value
    return inputs


def _typed_nodes(node):
    """Every dict anywhere under `node` that declares a dtype (stimela
    parameter schemas nest by parset namespace in the DDFacet schema)."""
    if isinstance(node, dict):
        if "dtype" in node:
            yield node
        else:
            for value in node.values():
                yield from _typed_nodes(value)


def _resolve_image(cab, doc):
    """Full image reference for a cab, resolving `_use` against the file's
    own vars block (both shapes used by the cab files: `ghcr.io` +
    `owner/name`, and `ghcr.io/owner` + `name`)."""
    image = {k: v for k, v in (cab.get("image") or {}).items() if k != "_use"}
    use = (cab.get("image") or {}).get("_use")
    if use:
        base = doc
        for part in use.split("."):
            base = base[part]
        for key, value in base.items():
            image.setdefault(key, value)
    registry = str(image.get("registry", "")).rstrip("/")
    name = str(image.get("name", ""))
    version = image.get("version")
    full = f"{registry}/{name}"
    if version:
        full = f"{full}:{version}"
    return full


def test_package_data_is_installed():
    """`(dde_cargo): <file>` includes resolve against the installed package
    directory, so every shipped YAML must be reachable as package data."""
    for name in (
        CABS_FILE,
        DDFACET_SCHEMA_FILE,
        KILLMS_SCHEMA_FILE,
        DDFACET_MEMORY_PLAN_FILE,
        KILLMS_MEMORY_PLAN_FILE,
        "pick-reference-ant.yml",
    ):
        assert _package_file(name).is_file(), f"{name} is missing from the package"


def test_cab_inventory(cabs):
    """The package must carry the full DD cab family from meerkat_imaging's
    cabs/ddfacet.yml."""
    assert set(cabs) == EXPECTED_CABS


def test_memory_plan_cabs_are_self_contained():
    """Each memory-plan file defines exactly its one cab, with its own image
    var (they are `_include`d alongside ddfacet.yml and must not depend on
    its vars block)."""
    for filename, cab_name in (
        (DDFACET_MEMORY_PLAN_FILE, "ddfacet-memory-plan"),
        (KILLMS_MEMORY_PLAN_FILE, "killms-memory-plan"),
    ):
        doc = _load(filename)
        assert set(doc.get("cabs") or {}) == {cab_name}
        cab = doc["cabs"][cab_name]
        assert cab["image"]["_use"].startswith(f"vars.{cab_name}")
        assert cab["flavour"]["kind"] == "python-code"


def test_ddfacet_inputs_expose_the_parset_schema(cabs):
    """Recipes bind DDFacet parset namespaces (Data.MS, Output.Name, ...),
    which arrive via the cab's `_include` of the generated inputs schema."""
    inputs = _merged_inputs(cabs["ddfacet"], cabs_doc)
    assert "parset" in inputs
    assert inputs["Data"]["MS"]["dtype"] == "List[MS]"
    assert inputs["Data"]["MS"]["policies"]["repeat"] == ","
    assert "Name" in inputs["Output"]
    for namespace in ("Image", "Facets", "Deconv", "Freq", "Weight"):
        assert namespace in inputs, f"missing parset namespace '{namespace}'"


def test_killms_inputs_expose_the_solve_schema(cabs):
    inputs = _merged_inputs(cabs["killms"], cabs_doc)
    for key in ("MSName", "InCol", "OutCol", "SolverType", "PolMode", "NChanSols"):
        assert key in inputs, f"missing killMS input '{key}'"
    # the memory-plan cab's outputs wire into these
    for key in ("NCPU", "TChunk"):
        assert key in inputs, f"missing killMS input '{key}'"


def test_list_inputs_declare_a_repeat_policy(cabs):
    """scabha refuses a List[...] input with no repeat policy at run time
    ("list-type parameter does not have a repeat policy set") -- an error no
    other check catches, so it must be pinned here."""
    checked = 0
    for cab_name, cab in cabs.items():
        for node in _typed_nodes(_merged_inputs(cab, cabs_doc)):
            if not str(node.get("dtype", "")).startswith("List["):
                continue
            checked += 1
            assert (node.get("policies") or {}).get("repeat"), (
                f"cab '{cab_name}': List[...] input has no repeat policy; "
                "scabha will refuse it at run time"
            )
    assert checked, "no list-typed inputs found -- this test would pass vacuously"


def test_no_input_output_name_collisions(cabs):
    """Stimela rejects a cab whose name appears in both inputs and outputs
    (the killms-memory-plan TChunk story)."""
    for cab_name, cab in cabs.items():
        inputs = {k for k in (cab.get("inputs") or {}) if k != "_include"}
        outputs = set(cab.get("outputs") or {})
        assert not inputs & outputs, (
            f"cab '{cab_name}': {inputs & outputs} appears in both inputs and outputs"
        )


def test_bdsf_catalog_is_an_image_override_fragment(cabs):
    """ddfacet.yml's `bdsf.catalog` entry carries only an image: it exists to
    override cult-cargo's `bdsf.catalog` cab (whose quay.io image is amd64-only)
    with the multi-arch ddfacet one.  A recipe must therefore include
    `(cultcargo): bdsf.yml` BEFORE `(dde_cargo): ddfacet.yml` -- upstream's
    white-belt-4-ddfacet.yml ordering -- or stimela fails to build the cab
    ("Missing mandatory value: cabs.bdsf.catalog.command")."""
    cab = cabs["bdsf.catalog"]
    assert set(cab) == {"image"}, (
        "bdsf.catalog must stay an image-only override fragment, otherwise the "
        "include-order requirement above changes"
    )


def test_every_cab_runs_on_a_pinned_tmolteno_image(cabs, cabs_doc):
    """A cab with no image is rejected by container backends; these cabs must
    all run on the multi-arch ghcr.io/tmolteno ddfacet/killms images, with an
    explicit version pin.

    The exact pin numbers are deliberately NOT asserted: the cab files are
    verbatim upstream copies, so a version bump upstream should re-publish
    without a test edit.
    """
    assert cabs_doc["vars"]["tim-molteno"]["images"]["registry"] == "ghcr.io"
    for cab_name, cab in cabs.items():
        full = _resolve_image(cab, cabs_doc)
        prefix = EXPECTED_IMAGE_PREFIXES.get(cab_name, DEFAULT_IMAGE_PREFIX)
        assert full.startswith(prefix + ":"), (
            f"cab '{cab_name}' runs on {full!r}, expected a {prefix}:<version> image"
        )
        version = full.rsplit(":", 1)[-1]
        assert version and version != full, f"cab '{cab_name}' has no image version pin"
