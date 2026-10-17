# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The release notes are assembled from the upstream source repositories:
DDFacet's `CHANGES.md` and commit history, killMS's commit history, and
`meerkat_imaging`'s pin commits on `main`.

## [Unreleased]

### Added

- `tasks.py`: invoke/plumbum release automation. It generates the changelog
  from the `../DDFacet` and `../killMS` commit history, bumps the package and
  image pins, runs the tests and build, pushes the tag that triggers the PyPI
  workflow, and creates the GitHub release with the built artifacts.
- `docs/cabs.md`: generated cab reference covering every packaged cab, its
  inputs, outputs, image and purpose, built from the YAMLs plus the curated
  `docs/cab_notes.yml`; `invoke docs` regenerates it and `invoke docs --check`
  verifies it is current.

## [0.1.1] - 2026-10-18

### Container images

- DDFacet `ghcr.io/tmolteno/ddfacet:v0.16.1` → `v0.16.6`, used by `ddfacet`,
  `ddfacet-memory-plan`, and the shared helper cabs (`ddf_makemodel`,
  `ddf_makemask`, `dilatemask`, `clustercat`, `ddfacet-get-npix`,
  `bdsf.catalog`, `modelcat`, `autofacet`, `snapnodes`).
- killMS `ghcr.io/tmolteno/killms:v3.15.3` → `v3.15.8`, used by `killms` and
  `killms-memory-plan`.
- Cabs re-copied verbatim from `meerkat_imaging` `main` (`68b7d55`). The
  upstream pin commits are `17ff66f` (v0.16.2/v3.15.4), `6d790e2`
  (v0.16.3/v3.15.5), `39dcdf0` (v0.16.4/v3.15.6), `f79a439`
  (v0.16.5/v3.15.7), and `529047a` (v0.16.6/v3.15.8). Cab bodies and schemas
  are unchanged; only the image pins differ.

### DDFacet v0.16.2

- **Dependencies removed:** numba, llvmlite and codex-africanus are gone. The
  WSCMS sub-minor-loop `substep` is numpy and the alpha-map fit is Rust;
  outputs are bit-identical. The deap subset DDFacet uses is vendored as
  `deaplite`.
- **Rust island GAs:** the SSD3 and SSD2 island GAs moved to GIL-free Rust
  (`ssd_ga.rs`), with per-island random streams. Seeded SSD2/SSD3 runs change
  bits; Python fallbacks remain for the uncovered paths.
- **Rust MultiSlice fit:** the SSD2/SSD3 MultiSlice spectral fit is a GIL-free
  port of SciPy's `trf` least squares. It changes SSD MultiSlice results at
  the 1e-12 (median) to 1e-7 (99th percentile) relative level and is much
  faster.
- **Fixes:** `--Deconv-Mode WSCMS` no longer crashes unpacking `NPSF` (#64);
  `--Deconv-Mode WSCMS2` is now selectable (#64); WSCMS no longer crashes when
  its last cleanable scale is retired (#65); `A_whereMax` now gives the same
  answer for every NCPU, including `NCPU=1` (#66).

### DDFacet v0.16.3

- **Result changes:** WSCMS/WSCMS2 scales are rounded to whole pixels (#77);
  the smooth beam is averaged with the imaging weights `W`, not `W²` (#69),
  changing `.int.*`, `.dirty.corr` and `SmoothNorm`; an explicit
  `PhaseCenterRADEC` within 1° of the equator keeps its declination sign
  (#73); SSD3's renormalisation threshold is relative to `MeanJonesNorm`
  (#71); the SSD GA move-pixel mutation pairs each spectral index with the
  correct flux (#70); the spectral fit uses each pixel's JonesNorm (#74a);
  the island GA PSF is scaled by the JonesNorm at the island (#72); SSD2
  Python-GA islands draw from per-island streams, making seeded runs
  reproducible (#79).
- **Fixes:** `ComputeDotUVW` skips single-row baselines instead of raising
  `IndexError` (#67); `ClusterCat.WriteTessel` skips degenerate Voronoi cells
  (#68); noise-map upsampling fills the correct final column and the FFTW
  wisdom directory no longer races (#74b,c); WSCMS2's frozen auto-mask now
  reaches its stopping checks (#75); WSCMS2 with `MaxMajorIter 1` no longer
  cleans nothing (#76).

### DDFacet v0.16.4

- **Threads:** the rayon global pool is sized from `Parallel.NCPU` instead of
  staying pinned at one thread (#80); `Parallel.MemWatermarkGB` is deprecated
  and documented as having no effect since v0.16.0 (#80).
- **Performance:** `ComputeDotUVW` is O(n log n) instead of
  O(baselines × rows); the FITS-beam Jones product is vectorised; BDA
  smear-mapping rows are grouped by antenna pair once; and the W-term
  convolution functions are computed in Rust without the GIL (#81). The
  W-term port is not bit-identical but agrees with the numpy path to better
  than 1e-5 of the plane maximum.

### DDFacet v0.16.5

- **Performance:** BDA smear mapping mode 1 (the default) is vectorised
  (#83), and the smooth beam is stacked for all directions in one pass (#84).
- **Fixes:** BDA mode 2 handles a single-row antenna pair as one time block
  (#82) and floors uv at 1e-10 like mode 1 (#85).

### DDFacet v0.16.6

- **Performance, bit-identical:** the logger only reads `/proc` when memory
  logging is on and caches the figures for 0.5 s (#86); each facet's W planes
  are unpacked once rather than per grid machine (#87); batch tasks pass the
  packed W planes instead of 2·Nw views (#88A); SSD3 and SSD2 HMP cache builds
  use every core (#89, #93); facet lookup uses a bounding-box prefilter and
  complete prefetch (#91); SSD3 island init renders each island model once
  for all three frequencies and skips zero slots (#92); facet- and
  chunk-invariant task setup is cached (#88B).

### killMS v3.15.4 – v3.15.8

- **v3.15.4:** rebuilt on DDFacet v0.16.2; no killMS code change.
- **v3.15.5:** rebuilt on DDFacet v0.16.3, with three fixes:
  - ResidAnt weights use each visibility channel's own Jones-channel
    statistics, and unsolved antennas get a neutral median weight (#42).
  - Input robustness: a single `--FlagAnts` name is no longer iterated
    character by character, KAFCA falls back to XX/YY noise when the cross-pols
    are unusable, and a singular Jones matrix raises instead of producing
    inf/NaN (#43).
  - A rephase target within 1° of the equator keeps its declination sign
    (#44).
- **v3.15.6 – v3.15.8:** rebuilt on DDFacet v0.16.4–v0.16.6; no changes to
  killMS code.

### Packaging

- Python 3.15 support: `requires-python` is now `>=3.10,<3.15`, with the
  matching `uv.lock` resolution.
- README image table updated and its documented Python window corrected to
  match `pyproject.toml`.

## [0.1.0] - 2026-10-14

### Added

- Initial release: stimela 2 cabs for DDFacet and killMS on amd64 and arm64,
  comprising `ddfacet.yml` (11 cabs) with its generated parameter schemas,
  plus the `ddfacet-memory-plan` and `killms-memory-plan` cabs.
- PyPI trusted publishing (OIDC) on `vX.Y.Z` tags.

[Unreleased]: https://github.com/tmolteno/dde-cargo/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/tmolteno/dde-cargo/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/tmolteno/dde-cargo/releases/tag/v0.1.0
