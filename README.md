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

## Icons and logos

Brand assets are included in two places:

- `custom_components/hyundai_bluelink/brand/` for Home Assistant's custom integration
  brand loader.
- `brand/` at the repository root for HACS repository views that look for
  repository-level brand assets.

If HACS still shows `icon not available` after updating, restart Home Assistant and
hard-refresh the browser. HACS may keep showing a cached placeholder until its pending
restart/update state clears.

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

## Engine controls

The **Start** button requests a five-minute engine run with air conditioning off.
The **Stop** button ends a remote engine run. Both use the request format for the
vehicle's protocol: CCS2 uses `command` and flat start settings; older vehicles use
`action` and nested start settings. Engine commands are sent once and never replayed
automatically after a failed request.

## Other remote controls

Lock/unlock, horn/lights, and window controls use the endpoint and payload for the
vehicle's protocol. **Horn** and **Horn / Light** both request Hyundai Australia's
combined horn-and-lights action; **Light** requests lights only.

Window actions first read the vehicle profile to select the supported window API.
**Window ventilation** requests the ventilation position, rather than fully opening
the windows. Vehicles that do not report the required capability return an explicit
unsupported-action error. These actions control windows only, including on vehicles
that also have powered curtains.

The [action request reference](docs/action-request-formats.md) documents all exposed
actions, their request bodies, and the source used to verify them. Contract tests
run without contacting Hyundai or operating a vehicle.

## Refresh behavior

The integration polls cached Hyundai data through one `DataUpdateCoordinator`.
In **Configure**, select a native Home Assistant **Schedule** helper and set the
intervals for inside and outside its time blocks (defaults: 5 and 60 minutes).
Without a schedule, or while it is unavailable, the outside interval applies.
Edit the calendar under **Settings > Devices & services > Helpers**; it supports
multiple blocks per day and uses Home Assistant's local time. Engine state does
not override the selected cadence. Request failures back off to the outside interval.

The car's **Vacation** switch pauses all requests for the account: automatic
polling, manual refreshes and remote controls. The setting survives restarts;
Home Assistant restores its last readings from a local telemetry snapshot without
logging in to Hyundai. Switch Vacation off to refresh and resume the schedule.
It is also available in Configure, including if there is no saved vehicle snapshot.
It does not change anything in the official Hyundai app or stop checks by other apps.
Automatic polling reads cached data; it never sends a live/force refresh to the car.

The GPS tracker exposes Hyundai's actual location observation time. Faster polling
does not guarantee live driving positions. See [car tracking and commute alerts](
docs/car-tracking.md) for map history, freshness attributes and an optional
Work-to-Home ETA notification blueprint.

Two refresh buttons are exposed:

- **Refresh**: refetches the cached Hyundai API status without requiring the PIN.
- **Live refresh**: calls the PIN-protected v2 live-status endpoint before the
  coordinator refetches vehicle status. This is useful when you want to ask Hyundai
  for newer car telemetry on demand.

Authentication tokens refresh automatically. If Hyundai rejects a refresh token or
a cached-data request, the integration attempts a fresh login with the saved
credentials. Concurrent requests share authentication recovery, and vehicle-control
commands are never automatically replayed. Temporary connection or server failures
remain retryable.

If Hyundai requests a password update or another account action, sign out and back
into the official Bluelink app and complete its prompts. Then use the Home Assistant
reauthentication repair with your current password. These interactive account steps
cannot be completed by automatic token refresh.

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
Mushroom and card-mod. It also references a vehicle image at
`/local/images/white_suv_top_down.png`, which maps to
`<Home Assistant config>/www/images/white_suv_top_down.png`.

## Development checks

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
python -m compileall custom_components tests
python -m ruff check .
```

[build-badge]: https://github.com/remy-burney/hyundai-bluelink/actions/workflows/validate.yml/badge.svg
[build-link]: https://github.com/remy-burney/hyundai-bluelink/actions/workflows/validate.yml
[downloads-badge]: https://img.shields.io/github/downloads/remy-burney/hyundai-bluelink/total?style=flat-square
[hacs-badge]: https://img.shields.io/badge/HACS-custom-orange.svg?style=flat-square
[hacs-button]: https://my.home-assistant.io/badges/hacs_repository.svg
[hacs-link]: https://my.home-assistant.io/redirect/hacs_repository/?owner=remy-burney&repository=hyundai-bluelink&category=integration
[release-badge]: https://img.shields.io/badge/release-v0.2.0-blue?style=flat-square
[releases-link]: https://github.com/remy-burney/hyundai-bluelink/releases
