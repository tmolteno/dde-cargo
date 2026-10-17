# dde-cargo
Stimela cabs for DDFacet/Killms on both arm64 and x86-64 systems.

The cab YAMLs in `dde_cargo/` are verbatim copies of `meerkat_imaging/cabs/`
(`ddfacet.yml`, its two `_include`d parameter schemas, and the two
memory-plan cabs). A change to a cab starts in that repository; copy it here,
bump the version, and tag. Release history is in [CHANGELOG.md](CHANGELOG.md).

## Cabs and images

| Cab | Image |
|---|---|
| `ddfacet` | `ghcr.io/tmolteno/ddfacet:v0.16.6` |
| `killms` | `ghcr.io/tmolteno/killms:v3.15.8` |
| `ddfacet-memory-plan` | `ghcr.io/tmolteno/ddfacet:v0.16.6` |
| `killms-memory-plan` | `ghcr.io/tmolteno/killms:v3.15.8` |
| `ddf_makemodel`, `ddf_makemask`, `dilatemask`, `clustercat`, `ddfacet-get-npix`, `bdsf.catalog`, `modelcat`, `autofacet`, `snapnodes` | `ghcr.io/tmolteno/ddfacet:v0.16.6` |

All images are published for amd64 and arm64.

## Install

```sh
pip install dde-cargo
```

Requires Python >= 3.10,< 3.15 (the same window as `skarabina-cargo`) and
installs `stimela>=2.1.4` — every cab runs in its container, so the host needs
nothing else.

## Usage

In a stimela 2 recipe, load the cabs from the installed package with
configuratt's package-include syntax. The `cultcargo` include must come first:
`ddfacet.yml` carries an image-only override for cult-cargo's `bdsf.catalog`
cab (the upstream image is amd64-only; these cabs redirect it to the
multi-arch ddfacet image), and stimela builds every cab at load time, so
`bdsf.yml` must already be loaded when `ddfacet.yml` merges in:

```yaml
_include:
  - (cultcargo):
      - bdsf.yml
  - (dde_cargo):
      - ddfacet.yml
      - ddfacet-memory-plan.yml
      - killms-memory-plan.yml
```

then reference them from steps:

```yaml
steps:
  ddfacet-target:
      cab: ddfacet
      params:
          Data.MS: mydata.ms
          Output.Name: target0
  killms-target:
      cab: killms
      params:
          MSName: mydata.ms
          InCol: CORRECTED_DATA
```

Only `ddfacet.yml` is essential; the memory-plan files are optional extras
(wire them ahead of a step as shown in their header comments — e.g.
`ddfacet-memory-plan` suggests `Parallel.NCPU`, `Data.ChunkHours` and
`Selection.ChanStep` for the imaging step that follows).

Notes carried over from the upstream cab comments:

* The `autofacet` cab imports `auto_facet_tool/auto_facet.py` from the
  *working directory*, so it needs a checkout of `meerkat_imaging` beside the
  recipe (stimela binds the working directory into the container).
* The memory-plan cabs pin their image "to whatever the recipe uses": a recipe
  with its own image var should override `image:` on the cab instead of
  editing the package.
* The DDFacet cab wraps every parset namespace (`Data`, `Image`, `Facets`,
  `Deconv`, ...) as dashed CLI options (`--Data-MS`, `--Image-NPix`, ...);
  the killMS cab passes its flat parameter set through `kMS.py`.

## Publishing

Trusted publishing (OIDC) — there is no API token. The GitHub Actions
workflow `.github/workflows/publish_pypi.yaml` fires on a `vX.Y.Z` tag, builds
with `uv`, and publishes from the `pypi` environment.

1. Register the pending publisher on PyPI (once):
   [pypi.org/manage/account/publishing](https://pypi.org/manage/account/publishing/)
   with owner `tmolteno`, repository `dde-cargo`, workflow `publish_pypi.yaml`,
   environment `pypi`. The workflow filename must match exactly.
2. Bump `version` in `pyproject.toml`.
3. `git commit -m "..." && git tag -a vX.Y.Z -m "..." && git push origin main --follow-tags`

The workflow run appears under the repo's Actions with the `pypi` environment;
the publish is live at [pypi.org/project/dde-cargo](https://pypi.org/project/dde-cargo/).

## Development

```sh
uv sync --all-groups
uv run pytest          # schema contracts for the packaged cabs
uv build               # wheel + sdist into dist/
```

An end-to-end smoke check (loads the cabs through stimela's real spec loader,
as a recipe would):

```sh
uv run stimela run /tmp/dde-cargo-smoke.yml dde-cargo-smoke -d
```

with `/tmp/dde-cargo-smoke.yml` any recipe that `_include`s the package as
shown above and runs one or two of the cabs.
