# Hyundai Bluelink for Home Assistant

[![HACS custom][hacs-badge]][hacs-link]
[![Release][release-badge]][releases-link]
[![Downloads][downloads-badge]][releases-link]
[![Build][build-badge]][build-link]

Custom component for Hyundai Bluelink Australia, using the Home Assistant domain
`hyundai_bluelink`.

This repository is structured so `custom_components/hyundai_bluelink` can be copied
into `homeassistant/components/hyundai_bluelink` later. For a Core submission, move
the bundled API adapter into an upstream `aiobluelink` package, publish it to PyPI,
restore the manifest requirement, remove the `version` key from `manifest.json`, and
add Home Assistant pytest coverage.

## Architecture

- Home Assistant owns config flow, entity setup, polling, and device/action exposure.
- Hyundai HTTP, authentication, token refresh, PIN handling, and command payloads are
  isolated behind the async client wrapper. The HACS build currently includes a local
  adapter so setup works before `aiobluelink` is published.
- All telemetry entities read from one `DataUpdateCoordinator`.
- Remote commands are exposed as Home Assistant entities first:
  - `lock` entity for lock/unlock.
  - `button` entities for cached refresh, live refresh, start engine, stop engine,
    horn, lights, and windows.

## HACS installation

Use this link to directly go to the repository in HACS:

[![Open HACS repository on My Home Assistant][hacs-button]][hacs-link]

1. Add this repository as a HACS custom repository of type **Integration**.
2. Install **Hyundai Bluelink**.
3. Restart Home Assistant.
4. Add **Hyundai Bluelink** from **Settings > Devices & services**.

## Remote-control PIN

The remote-control PIN is the short security PIN used by the official Hyundai
Bluelink mobile app when you run remote actions such as lock, unlock, start engine,
stop engine, horn, lights, or window control.

It is not your Hyundai account password. Status-only entities such as range, fuel,
battery, doors, windows, and location can work without the PIN, but PIN-protected
remote commands will fail until it is configured.

To find, set, or reset it in the mobile app:

1. Open the official Hyundai Bluelink app.
2. Open **More** or **Settings**.
3. Look for **PIN**, **Remote control PIN**, **Security PIN**, or **Change PIN**.
4. If the app asks for a PIN when you run a remote action, use that same PIN here.
5. If you forgot it, use the app's reset/change PIN flow.

To add or change the PIN in Home Assistant after setup:

1. Go to **Settings > Devices & services**.
2. Open **Hyundai Bluelink**.
3. Select **Configure**.
4. Enter the remote-control PIN and submit.
5. Restart Home Assistant if the Configure button does not appear immediately after a
   HACS update.

## Refresh behavior

The integration polls cached Hyundai Bluelink vehicle data every 5 minutes through
one `DataUpdateCoordinator`. All sensors, binary sensors, locks, buttons, and device
trackers read from that shared coordinator data.

Two refresh buttons are exposed:

- **Refresh**: refetches the cached Hyundai API status without requiring the PIN.
- **Live refresh**: calls the PIN-protected v2 live-status endpoint before the
  coordinator refetches vehicle status. This is useful when you want to ask Hyundai
  for newer car telemetry on demand.

## Translations

Translation files are included for common Home Assistant locales. They currently use
the English source strings as safe fallback text until native translations are
reviewed and updated per language.

## Dashboard example

An example Lovelace YAML dashboard is available in
[docs/lovelace-dashboard.yaml](docs/lovelace-dashboard.yaml).

The example is based on a vehicle named `SANTA FE`, so it uses entity IDs such as
`sensor.santa_fe_range`, `lock.santa_fe_lock`, and
`binary_sensor.santa_fe_engine_running`. Replace `santa_fe` with the entity slug Home
Assistant creates for your vehicle.

The dashboard example assumes these optional HACS frontend cards are installed:
Mushroom, card-mod, and slider-entity-row. It also references a vehicle image at
`/local/images/white_suv_top_down.png`, which maps to
`<Home Assistant config>/www/images/white_suv_top_down.png`.

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
[release-badge]: https://img.shields.io/badge/release-v0.1.4-blue?style=flat-square
[releases-link]: https://github.com/remy-burney/hyundai-bluelink/releases
