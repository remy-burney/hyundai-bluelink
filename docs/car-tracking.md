# Car location and commute alerts

The integration exposes `device_tracker.<vehicle>_location`. Use a native map
card with `hours_to_show: 24` to show the recorded positions. The line connects
samples; it is not a road-matched route. Home Assistant Recorder must include the
tracker. Its usual retention is 10 days unless configured otherwise; the map's
24-hour display does not extend retention or recover missing positions.

The coordinator reads Hyundai's cached status and `/location/park` endpoint on
an editable weekly schedule. Create a **Schedule** helper in
**Settings > Devices & services > Helpers**, draw the desired time blocks, and
select it in the Bluelink integration's **Configure** dialog. Set both check
intervals there: the defaults are five minutes during a block and hourly otherwise.
For weekday commutes, add 06:00-09:00 and 15:00-17:00 on Monday through Friday.
The calendar follows Home Assistant's local timezone, including daylight saving.
No selected/available schedule uses the outside interval. Engine state does not
increase polling beyond the schedule; connection failures back off to the outside
interval. A block starting prompts a check when it increases polling frequency.
Detecting a new journey can take up to the selected interval, plus Hyundai's
reporting delay. No PIN-protected force refresh is sent
automatically. There is no published guarantee of continuous driving positions
from this endpoint, and faster polling cannot create missing GPS samples.

**Vacation** is a switch on the car device and an option in Configure. It pauses
every vehicle on that Bluelink account, including login, discovery, scheduled
polling, manual refreshes and remote controls. It persists over restarts and loads
the last known telemetry from Home Assistant's local storage. Saved readings keep
their original source timestamps. Credentials/tokens are not part of that snapshot.
Pending requests are cancelled; a request already delivered to Hyundai cannot be
retracted. Turning Vacation off refreshes the data and resumes the chosen cadence.
This setting affects this integration only, not Hyundai's app or other integrations.

Tracker attributes:

| Attribute | Meaning |
| --- | --- |
| `location_updated_at` | Hyundai GPS observation time, in UTC ISO format |
| `status_updated_at` | Vehicle status observation time, in UTC ISO format |
| `heading` | Heading associated with the location response |
| `location_source` | Identifies Hyundai's cached location |
| `poll_interval_seconds` | Current requested polling interval; null during Vacation |
| `polling_paused` | True while Vacation blocks all Bluelink requests |

AU location and legacy-status times use Australia/Sydney with daylight saving.
CCS2 vehicle `Date` is UTC. A successful API request does not advance either
timestamp. Missing timestamps remain unknown. Invalid coordinate pairs are
rejected; missing or older location responses preserve the previous valid fix
and its original timestamp. Embedded CCS2 location is not used because the AU
upstream client identifies it as stale.
Ambiguous or nonexistent local times at daylight-saving transitions are unknown;
the API provides no UTC offset to resolve them safely.

## Work to Home notification

The blueprint `blueprints/automation/car_departure_eta.yaml` is for an Australian
Home Assistant instance using metric units. Configure the Work zone first. Add
Waze Travel Time only after approving the sharing of the car's and destination's
coordinates with Waze. HACS installs the integration; import the optional
[commute blueprint](https://github.com/remy-burney/hyundai-bluelink/blob/v0.2.0/blueprints/automation/car_departure_eta.yaml)
separately using **Settings > Automations & scenes > Blueprints > Import blueprint**.
Create an automation from the blueprint and select the
car tracker, departure zone, destination zone, and your notification action. Set
the action's message field to `{{ commute_message }}`.

The automation requires a GPS fix no older than three minutes. After leaving
Work, it requires progress of at least 500 metres toward Home compared with the
last position inside Work. The fresh departure fix counts as the first approach
sample. The default of one confirmation sample allows short commutes to announce
promptly; increase **Direction confirmation samples** to two or three to require
additional successive updates moving at least 100 metres closer per update.
Confirmation must occur within 20 minutes. It stops
without sending if Vacation is on, GPS updates cease for 15 minutes, data becomes stale, or the car returns to
Work or reaches Home before confirmation. It requests a traffic-aware route ETA
once after confirmation; if Waze fails it sends a departure message without an
invented ETA. It suppresses further departures until arrival, return to Work or
four hours. Restarting Home Assistant cancels an in-flight automation and can
miss that trip; it does not replay departures from stored history.
With one confirmation sample, five-minute polling can announce at the first
observed departure; each extra sample adds roughly five minutes. Hourly polling
can miss a whole commute. Prefer frequent-check blocks covering the journeys you want to
monitor; the blueprint does not override your battery-saving polling policy.

Heading toward Home is an inference and can be wrong where routes share their
first section. The notification says "appears to be heading" and "estimated".
If Hyundai does not publish fresh positions during a drive, this automation
deliberately does not alert. A dedicated vehicle GPS tracker is then needed for
reliable moving-car tracking; a phone tracker follows its owner, not necessarily
the car.

For a speaker announcement, select a `tts.speak` action with your TTS provider as
the target and your speaker as `media_player_entity_id`. Use
`message: "{{ commute_message }}"`. Any existing quiet-mode helper can be checked
in this action sequence before speaking. The automation calls Waze only after
direction confirmation, and Vacation cancels it. Waze's integration can use fixed
Work/Home zones with **Enable polling for changes** turned off in its system
options; the automation's action requests a fresh traffic-aware ETA on demand.

Sources: [HA map card](https://www.home-assistant.io/dashboards/map/),
[Schedule helper](https://www.home-assistant.io/integrations/schedule/),
[Waze travel-time action](https://www.home-assistant.io/actions/waze_travel_time.get_travel_times/),
[AU upstream source](https://github.com/Hyundai-Kia-Connect/hyundai_kia_connect_api/blob/master/hyundai_kia_connect_api/KiaUvoApiAU.py),
[CCS2 UTC parsing](https://github.com/Hyundai-Kia-Connect/hyundai_kia_connect_api/blob/master/hyundai_kia_connect_api/ApiImplType1.py).
