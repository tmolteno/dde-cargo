# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-10-18

### Changed

- Pin the DDFacet image to `ghcr.io/tmolteno/ddfacet:v0.16.6` (was
  `v0.16.1`) for `ddfacet`, `ddfacet-memory-plan`, and the shared helper cabs
  (`ddf_makemodel`, `ddf_makemask`, `dilatemask`, `clustercat`,
  `ddfacet-get-npix`, `bdsf.catalog`, `modelcat`, `autofacet`, `snapnodes`).
- Pin the killMS image to `ghcr.io/tmolteno/killms:v3.15.8` (was `v3.15.3`)
  for `killms` and `killms-memory-plan`.
- Re-copy the packaged cabs verbatim from `meerkat_imaging` `main`
  (`68b7d55`); the cab bodies and schemas are unchanged apart from the image
  pins.
- Update the README image table to match the new pins.

### Added

- Python 3.15 support: `requires-python` is now `>=3.10,<3.15`, with the
  matching `uv.lock` resolution.

### Fixed

- The README's documented Python window now matches `pyproject.toml`.

## [0.1.0] - 2026-10-14

### Added

- Initial release: stimela 2 cabs for DDFacet and killMS on amd64 and arm64,
  comprising `ddfacet.yml` (11 cabs) with its generated parameter schemas,
  plus the `ddfacet-memory-plan` and `killms-memory-plan` cabs.
- PyPI trusted publishing (OIDC) on `vX.Y.Z` tags.

[Unreleased]: https://github.com/tmolteno/dde-cargo/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/tmolteno/dde-cargo/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/tmolteno/dde-cargo/releases/tag/v0.1.0
