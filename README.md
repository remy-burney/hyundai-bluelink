# Hyundai Bluelink for Home Assistant

[![HACS custom][hacs-badge]][hacs-link]
[![Release][release-badge]][releases-link]
[![Downloads][downloads-badge]][releases-link]
[![Build][build-badge]][build-link]

Custom component scaffold for Hyundai Bluelink Australia, using the Home Assistant
domain `hyundai_bluelink`.

This repository is structured so `custom_components/hyundai_bluelink` can be copied
into `homeassistant/components/hyundai_bluelink` later. For a Core submission, remove
the `version` key from `manifest.json`, publish the upstream `aiobluelink` package to
PyPI, and add Home Assistant pytest coverage.

## Architecture

- Home Assistant owns config flow, entity setup, polling, and device/action exposure.
- Hyundai HTTP, authentication, token refresh, PIN handling, and command payloads belong
  in the standalone async upstream package `aiobluelink`.
- All telemetry entities read from one `DataUpdateCoordinator`.
- Remote commands are exposed as Home Assistant entities first:
  - `lock` entity for lock/unlock.
  - `button` entities for start engine, stop engine, horn, lights, windows, and refresh.

## HACS installation

Use this link to directly go to the repository in HACS:

[![Open HACS repository on My Home Assistant][hacs-button]][hacs-link]

1. Add this repository as a HACS custom repository of type **Integration**.
2. Install **Hyundai Bluelink**.
3. Restart Home Assistant.
4. Add **Hyundai Bluelink** from **Settings > Devices & services**.

The integration currently expects an async upstream library named `aiobluelink` to be
available from PyPI via the manifest requirement.

## Development checks

```powershell
python -m pytest tests -q
python -m compileall custom_components tests
```

[build-badge]: https://github.com/remy-burney/hyundai-bluelink/actions/workflows/validate.yml/badge.svg
[build-link]: https://github.com/remy-burney/hyundai-bluelink/actions/workflows/validate.yml
[downloads-badge]: https://img.shields.io/github/downloads/remy-burney/hyundai-bluelink/total?style=flat-square
[hacs-badge]: https://img.shields.io/badge/HACS-custom-orange.svg?style=flat-square
[hacs-button]: https://my.home-assistant.io/badges/hacs_repository.svg
[hacs-link]: https://my.home-assistant.io/redirect/hacs_repository/?owner=remy-burney&repository=hyundai-bluelink&category=integration
[release-badge]: https://img.shields.io/badge/release-v0.1.0-blue?style=flat-square
[releases-link]: https://github.com/remy-burney/hyundai-bluelink/releases
