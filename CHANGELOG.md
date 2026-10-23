# Changelog

Notable changes to evo.locate, newest first. Each entry links the pull request that made it.

Versions have five parts, `v{major}.{rc}.{beta}.{alpha}.{build}`, and the build number
advances once per release. New changes go under Unreleased in the same pull request,
and the release moves them under its version.

## Unreleased

## v0.0.0.1.8 - 2026-10-08

### Maintenance

- run tests on pull requests only, not again on push to main ([#28](https://github.com/evomedia-net/evo.locate/pull/28))
- **ci:** re-run a test run once when a job in it times out ([#27](https://github.com/evomedia-net/evo.locate/pull/27))
- **ci:** stop a hung test run after 5 minutes instead of GitHub's 6 hours ([#26](https://github.com/evomedia-net/evo.locate/pull/26))
- retire the SmartPlant EHS name from the port comment ([#25](https://github.com/evomedia-net/evo.locate/pull/25))

## v0.0.0.1.7 - 2026-09-13

A release stamp only: no other change since the previous release.

## v0.0.0.1.6 - 2026-09-12

### Documentation

- **security:** project security notes, and twins for every root .md ([#20](https://github.com/evomedia-net/evo.locate/pull/20))

## v0.0.0.1.5 - 2026-09-11

### Added

- **release:** refuse to build a zip whose name would not match its contents ([#17](https://github.com/evomedia-net/evo.locate/pull/17))
- **release:** make every release downloadable and verifiable ([#16](https://github.com/evomedia-net/evo.locate/pull/16))

### Fixed

- **locate:** a version bump never reached production - /health read a hardcoded literal and the image never changed ([#15](https://github.com/evomedia-net/evo.locate/pull/15))

## v0.0.0.1.4 - 2026-08-31

### Fixed

- add pytest-cov to requirements-dev.txt so coverage can be measured ([#11](https://github.com/evomedia-net/evo.locate/pull/11))

### Documentation

- **readme:** add mkdir/chown for the data dir to the systemd service steps ([#5](https://github.com/evomedia-net/evo.locate/pull/5))

### Maintenance

- cover the download/refresh machinery and error paths - 70% -> 97.9% ([#12](https://github.com/evomedia-net/evo.locate/pull/12))
- run the test suite on every PR, and fail if a test skips ([#8](https://github.com/evomedia-net/evo.locate/pull/8))
- point repo URLs at evomedia-net/evo.* ([#6](https://github.com/evomedia-net/evo.locate/pull/6))

## v0.0.0.1.3 - 2026-08-06

### Maintenance

- add Evomedia.net header (repo URL, author, MIT) to every code file ([#4](https://github.com/evomedia-net/evo.locate/pull/4))

## v0.0.0.1.2 - 2026-08-06

### Documentation

- **readme:** plain-text README.txt mirror + run-without-Docker and troubleshooting sections ([#3](https://github.com/evomedia-net/evo.locate/pull/3))

## v0.0.0.1.1 - 2026-08-06

### Added

- **api:** root redirect to /docs, hostname lookups, pretty-printed JSON ([#2](https://github.com/evomedia-net/evo.locate/pull/2))
- evo.locate - self-hosted IP geolocation API

### Maintenance

- move evo.locate off port 8080 (taken by SmartPlantEHS dev and DocketMail prod) to 9100 ([#1](https://github.com/evomedia-net/evo.locate/pull/1))
