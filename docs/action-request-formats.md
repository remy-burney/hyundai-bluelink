# Australian Bluelink action request reference

Audited on 2026-09-20 against the Australian Android app supplied with this project
(`com.hyundai.bluelink.aus`, APK SHA-256
`D3C308BD12521C029412BEB3CF28CDBA865F084C4B23CB3DDEA6EA7AC6860811`).
The table covers all ten integration actions and the lock entity's two actions.
It describes request contracts, not successful physical vehicle tests.

## Authorization

All vehicle actions except cached refresh first obtain a control token with
`PUT /api/v1/user/pin`, an access-token Authorization header, and
`{"deviceId":"<registered device>","pin":"<configured PIN>"}`.
The actual control request uses that control token as its Bearer Authorization.
The `ccsp-device-id` header is retained and `Ccuccs2protocolsupport` carries the
reported integer protocol version, including values greater than one.

PIN submissions and control requests are never automatically replayed, including
after authentication errors, server errors, or timeouts. Cached GET requests may
recover authentication and retry once. A live-status GET is a control request and
does not use that retry path.

## Controls

All rows below use POST. Legacy paths have the prefix
`/api/v2/spa/vehicles/{vehicleId}/control/`; CCS2 paths use
`/api/v2/spa/vehicles/{vehicleId}/ccs2/control/`.
`deviceId` below means the registered application device, not the vehicle ID.

| Action | Legacy suffix and JSON body | CCS2 suffix and JSON body |
| --- | --- | --- |
| Lock | `door` — `{"deviceId":"…","action":"close"}` | `door` — `{"command":"close"}` |
| Unlock | `door` — `{"deviceId":"…","action":"open"}` | `door` — `{"command":"open"}` |
| Start | `engine` — `{"action":"start","options":{"airCtrl":0,"igniOnDuration":5}}` | `engine` — `{"command":"start","hvacCtrl":0,"ignitionDuration":5}` |
| Stop | `engine` — `{"deviceId":"…","action":"stop"}` | `engine` — `{"command":"stop"}` |
| Horn | `horn` — `{"deviceId":"…"}` | `hornlight` — `{"command":"on"}` |
| Horn / Light | `horn` — `{"deviceId":"…"}` | `hornlight` — `{"command":"on"}` |
| Light | `light` — `{"deviceId":"…"}` | `light` — `{"command":"on"}` |
| Open windows, basic API | `window` — `{"deviceId":"…","action":"open"}` | `window` — `{"command":"open"}` |
| Close windows, basic API | `window` — `{"deviceId":"…","action":"close"}` | `window` — `{"command":"close"}` |
| Open windows, extended API | `windowcurtain` — per-window position `1` | `windowcurtain` — per-window position `1` |
| Close windows, extended API | `windowcurtain` — per-window position `0` | `windowcurtain` — per-window position `0` |
| Window ventilation | `windowcurtain` — per-window position `2` | `windowcurtain` — per-window position `2` |

The five-minute, air-conditioning-off start is this integration's default. Horn
and Horn / Light are aliases for the app's combined action. The legacy API has no
separate `hornlight` route in the app's control interface.

## Window capabilities and position bodies

Before a window control, read `GET /api/v1/spa/vehicles/{vehicleId}/profile` with
the access token. Profile data is in `resMsg.vinInfo[0]`, not `resMsg.profiles`.

| Profile capabilities | Request selection |
| --- | --- |
| `option.windowSafetyOption == 1`, `option.windowSafetyOption2` absent or `-1`, and `serviceOption.windowControlOption` absent or `-1` | Basic `window` open/close; no ventilation |
| Same safety flags, with `windowControlOption` present | Extended `windowcurtain`; ventilation only for option `2` or `3` |
| `option.windowSafetyOption2 == 3` | Extended `windowcurtain`, including ventilation |
| Neither safety condition | Reject window control before PIN submission |

An extended legacy body contains `deviceId` plus `frontLeft`, `frontRight`,
`backLeft`, and `backRight`, all set to the requested numeric position.
An extended CCS2 body contains `drvSeatWindow`, `psgSeatWindow`, `rlSeatWindow`,
and `rrSeatWindow`, all set to that position. It also includes `drvSeatLoc` from
the profile's `option` object when nonempty. These bodies have no `action` or
`command` key. Curtain keys are omitted; nulls and invented curtain positions
must not be sent. This integration requests window movement only, whereas the
vendor UI combines some window actions with curtain movement on equipped cars.

## Refresh actions

| Action | Legacy GET path | CCS2 GET path | Authorization |
| --- | --- | --- | --- |
| Refresh | `/api/v1/spa/vehicles/{vehicleId}/status/latest` | `/api/v1/spa/vehicles/{vehicleId}/ccs2/carstatus/latest` | Access token |
| Live refresh | `/api/v2/spa/vehicles/{vehicleId}/status` | `/api/v2/spa/vehicles/{vehicleId}/ccs2/carstatus` | Control token |

Both GET requests have no JSON body.

## Previous command still processing (4004)

Hyundai's `resCode: 4004` is a pending-command rejection, not evidence of a
malformed lock body. The vendor app maps it to `remote.duplicate`; its English
`watch_error_response_4004` resource describes execution of the previous remote
control command. The integration displays that explanation for both HTTP 400
and failed HTTP 200 responses. It does not retry or assume the command succeeded.

Controls for one vehicle cannot overlap while Home Assistant is awaiting a
control request. A second control is rejected locally rather than queued;
cached refresh remains available. Hyundai may still be processing an accepted
command after the HTTP request returns, including commands from its own app.
In that case 4004 can still occur. The lock entity shows Hyundai's last reported
state, which may lag physical completion; it is never optimistically set locked.

## Source and verification

Source evidence comes from the app's Retrofit interfaces `ControlUseTokenApi`,
`VehicleApi`, and `AccountApi`; `RemoteRepository.Command`; repository helpers
`H.c` and `H.d`; `RemoteViewModel` command handlers; the `w6.a` window capability
selectors; the `VehicleProfilePayload` serialization annotations; and the
`F6.d` request interceptor. Null-field behavior follows the control Retrofit
instance's Gson configuration in `F6.e`.

`tests/test_vehicle_commands.py` and `tests/test_engine_commands.py` exercise the
real client with a scripted HTTP transport. They check endpoints, JSON bodies,
capability selection, authorization, protocol headers, and failed-command retry
behavior. They do not contact Hyundai. Backend acceptance and physical behavior
still require a user-initiated test with a supported vehicle.
