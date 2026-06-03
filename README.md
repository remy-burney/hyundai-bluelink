# Hyundai Bluelink for Home Assistant

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

