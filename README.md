# dde-cargo

[![PyPI](https://img.shields.io/pypi/v/dde-cargo.svg)](https://pypi.org/project/dde-cargo/)

[Stimela](https://github.com/caracal-pipeline/stimela) cabs for
DDFacet/Killms on both arm64 and x86-64 systems.

DDFacet is a direction-dependent radio-interferometric imager: it grids
visibilities and deconvolves wide fields in facets, applying per-direction
Jones terms and primary beams. killMS is its companion calibration engine,
solving per-antenna, per-direction complex gains against a sky model. Together
they form the imaging and direction-dependent calibration halves of the DDE
loop. Release history is in [CHANGELOG.md](CHANGELOG.md).

## Cabs and images

Full parameter reference: [docs/cabs.md](https://github.com/tmolteno/dde-cargo/blob/main/docs/cabs.md).

| Cab | Purpose | Image |
|---|---|---|
| [`bdsf.catalog`][cab-bdsf-catalog] | Image-only override for cult-cargo's PyBDSF step | `ghcr.io/tmolteno/ddfacet:v0.16.6` |
| [`ddfacet`][cab-ddfacet] | Direction-dependent imager, gridder and deconvolver | `ghcr.io/tmolteno/ddfacet:v0.16.6` |
| [`killms`][cab-killms] | Direction-dependent gain solver | `ghcr.io/tmolteno/killms:v3.15.8` |
| [`ddf_makemodel`][cab-ddf-makemodel] | Build a direction catalogue from a DS9 region | `ghcr.io/tmolteno/ddfacet:v0.16.6` |
| [`ddf_makemask`][cab-ddf-makemask] | Make a FITS clean mask from a restored image | `ghcr.io/tmolteno/ddfacet:v0.16.6` |
| [`dilatemask`][cab-dilatemask] | Dilate a clean mask by N synthesised beams | `ghcr.io/tmolteno/ddfacet:v0.16.6` |
| [`clustercat`][cab-clustercat] | Cluster sources into DD direction nodes | `ghcr.io/tmolteno/ddfacet:v0.16.6` |
| [`ddfacet-get-npix`][cab-ddfacet-get-npix] | Compute the padded image size DDFacet needs | `ghcr.io/tmolteno/ddfacet:v0.16.6` |
| [`modelcat`][cab-modelcat] | Replace BDSF catalogue fluxes with model flux | `ghcr.io/tmolteno/ddfacet:v0.16.6` |
| [`autofacet`][cab-autofacet] | Derive facet centres from the DI products | `ghcr.io/tmolteno/ddfacet:v0.16.6` |
| [`snapnodes`][cab-snapnodes] | Snap DD nodes onto their dominant modelled source | `ghcr.io/tmolteno/ddfacet:v0.16.6` |
| [`ddfacet-memory-plan`][cab-ddfacet-memory-plan] | Suggest DDFacet memory and parallel settings | `ghcr.io/tmolteno/ddfacet:v0.16.6` |
| [`killms-memory-plan`][cab-killms-memory-plan] | Suggest killMS memory and parallel settings | `ghcr.io/tmolteno/killms:v3.15.8` |

All images are published for amd64 and arm64.

[cab-bdsf-catalog]: https://github.com/tmolteno/dde-cargo/blob/main/docs/cabs.md#cab-bdsf-catalog
[cab-ddfacet]: https://github.com/tmolteno/dde-cargo/blob/main/docs/cabs.md#cab-ddfacet
[cab-killms]: https://github.com/tmolteno/dde-cargo/blob/main/docs/cabs.md#cab-killms
[cab-ddf-makemodel]: https://github.com/tmolteno/dde-cargo/blob/main/docs/cabs.md#cab-ddf-makemodel
[cab-ddf-makemask]: https://github.com/tmolteno/dde-cargo/blob/main/docs/cabs.md#cab-ddf-makemask
[cab-dilatemask]: https://github.com/tmolteno/dde-cargo/blob/main/docs/cabs.md#cab-dilatemask
[cab-clustercat]: https://github.com/tmolteno/dde-cargo/blob/main/docs/cabs.md#cab-clustercat
[cab-ddfacet-get-npix]: https://github.com/tmolteno/dde-cargo/blob/main/docs/cabs.md#cab-ddfacet-get-npix
[cab-modelcat]: https://github.com/tmolteno/dde-cargo/blob/main/docs/cabs.md#cab-modelcat
[cab-autofacet]: https://github.com/tmolteno/dde-cargo/blob/main/docs/cabs.md#cab-autofacet
[cab-snapnodes]: https://github.com/tmolteno/dde-cargo/blob/main/docs/cabs.md#cab-snapnodes
[cab-ddfacet-memory-plan]: https://github.com/tmolteno/dde-cargo/blob/main/docs/cabs.md#cab-ddfacet-memory-plan
[cab-killms-memory-plan]: https://github.com/tmolteno/dde-cargo/blob/main/docs/cabs.md#cab-killms-memory-plan

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

### Automated release

`invoke release` drives the tag, PyPI publish and GitHub release end to end.
See [Release automation](#release-automation) under Development for the full
task reference and prerequisites.

### Manual release

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
uv run pytest          # schema + generated-docs contracts
uv build               # wheel + sdist into dist/
invoke --list          # tasks: version, changelog, docs, release
invoke docs            # regenerate docs/cabs.md
invoke docs --check    # verify docs/cabs.md is current
```

An end-to-end smoke check (loads the cabs through stimela's real spec loader,
as a recipe would):

```sh
uv run stimela run /tmp/dde-cargo-smoke.yml dde-cargo-smoke -d
```

with `/tmp/dde-cargo-smoke.yml` any recipe that `_include`s the package as
shown above and runs one or two of the cabs.

### Release automation

`tasks.py` is an [invoke](https://www.pyinvoke.org/) +
[plumbum](https://plumbum.readthedocs.io/) script that automates a release
from the sibling `../DDFacet` and `../killMS` repositories. It reads the
current image pins, resolves the latest upstream release tags, and generates
the changelog from the commits between those tags.

Prerequisites:

* the `dev` dependency group — `uv sync --all-groups` installs `invoke` and
  `plumbum`;
* `uv` and an authenticated `gh` (the PyPI workflow uses OIDC, so no API token
  is involved);
* `../DDFacet` and `../killMS` checkouts containing their `vX.Y.Z` release
  tags — override the paths with `DDFACET_REPO` and `KILLMS_REPO`;
* a clean `main` branch, with the package version not yet tagged or published.

Available tasks:

```sh
invoke --list                  # show the available release tasks
invoke version                 # package version and pinned/latest image tags
invoke changelog               # print the next release's changelog section
invoke changelog --allow-same  # ... even when no image tag has moved
invoke docs                    # regenerate docs/cabs.md
invoke docs --check            # verify docs/cabs.md is current
invoke release --dry-run       # show the complete plan; change nothing
invoke release --part patch    # the real release
```

`invoke version` reports the package version, the DDFacet/killMS tags currently
pinned by the cabs, and the latest tags in the upstream checkouts.

`invoke changelog` prints the section that would be inserted into
`CHANGELOG.md`. It groups the upstream commits per release tag (for example
`v0.16.2` … `v0.16.6`) and notes killMS releases that are rebuilds on a new
DDFacet image.

`invoke docs` regenerates the cab reference from the packaged YAMLs and
`docs/cab_notes.yml`; `invoke docs --check` reports whether the checked-in
`docs/cabs.md` is current.

`invoke release` performs the complete chain:

1. generates and inserts the changelog section, keeping any `[Unreleased]`
   notes;
2. bumps `version` in `pyproject.toml`, updates the DDFacet/killMS pins in the
   cab YAMLs and the image table above, and regenerates `docs/cabs.md`;
3. refreshes `uv.lock`, runs the test suite and `uv build`;
4. commits the changes, creates an annotated `vX.Y.Z` tag, and pushes `main`
   and the tag;
5. waits for the tag's `publish_pypi.yaml` workflow to succeed and verifies
   that the version is live on PyPI;
6. creates the GitHub release with the generated notes and the built wheel and
   sdist attached.

Options:

* `--part patch|minor|major` — which part of the package version to bump
  (default `patch`);
* `--ddfacet-tag` / `--killms-tag` — override the upstream target tags
  (default: the latest release tag in each checkout);
* `--allow-same` — release packaging-only changes when both images are already
  at the pinned tags;
* `--fetch` / `--no-fetch` — fetch upstream tags first (default: fetch, falling
  back to the local tags with a warning if the remotes are unreachable);
* `--yes` — skip the confirmation prompt;
* `--dry-run` — print the plan and generated changelog without changing,
  committing or publishing anything.

The script refuses to run on a dirty tree, from a branch other than `main`, or
when the target tag or PyPI version already exists. It never force-pushes.
