from __future__ import annotations

from datetime import timedelta

DOMAIN = "hyundai_bluelink"

CONF_PIN = "pin"
CONF_REGION = "region"
DEFAULT_REGION = "AU"

ATTR_VEHICLE_ID = "vehicle_id"

CONF_POLLING_SCHEDULE = "polling_schedule"
CONF_ACTIVE_INTERVAL = "active_interval"
CONF_IDLE_INTERVAL = "idle_interval"
CONF_VACATION = "vacation"
DEFAULT_ACTIVE_INTERVAL = 5
DEFAULT_IDLE_INTERVAL = 60
DEFAULT_SCAN_INTERVAL = timedelta(minutes=DEFAULT_IDLE_INTERVAL)

MANUFACTURER = "Hyundai"
