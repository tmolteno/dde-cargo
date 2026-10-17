# dde-cargo

[![PyPI](https://img.shields.io/pypi/v/dde-cargo.svg)](https://pypi.org/project/dde-cargo/)

[Stimela](https://github.com/caracal-pipeline/stimela) cabs for
DDFacet/Killms on both arm64 and x86-64 systems.

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
uv run pytest          # schema contracts for the packaged cabs
uv build               # wheel + sdist into dist/
invoke --list          # release tasks: version, changelog, release
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
invoke release --dry-run       # show the complete plan; change nothing
invoke release --part patch    # the real release
```

`invoke version` reports the package version, the DDFacet/killMS tags currently
pinned by the cabs, and the latest tags in the upstream checkouts.

`invoke changelog` prints the section that would be inserted into
`CHANGELOG.md`. It groups the upstream commits per release tag (for example
`v0.16.2` … `v0.16.6`) and notes killMS releases that are rebuilds on a new
DDFacet image.

`invoke release` performs the complete chain:

1. generates and inserts the changelog section, keeping any `[Unreleased]`
   notes;
2. bumps `version` in `pyproject.toml`, refreshes `uv.lock`, and updates the
   DDFacet/killMS pins in the cab YAMLs and the image table above;
3. runs the test suite and `uv build`;
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
