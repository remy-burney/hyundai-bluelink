# Hyundai Bluelink Home Assistant Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Home Assistant `hyundai_bluelink` integration scaffold that can be used as a HACS custom component now and moved into Home Assistant Core once the upstream async Bluelink client and tests are complete.

**Architecture:** The integration depends on a standalone async `aiobluelink` client for authentication, token refresh, vehicle telemetry, and vehicle control actions. Home Assistant code owns config flow, config-entry lifecycle, coordinator polling, entity descriptions, device metadata, and action exposure only.

**Tech Stack:** Home Assistant config entries, `DataUpdateCoordinator`, entity platforms, HACS custom component metadata, `pytest` for pure parser/action helper tests.

---

### Task 1: Repository Bootstrap

**Files:**
- Create: `custom_components/hyundai_bluelink/manifest.json`
- Create: `custom_components/hyundai_bluelink/const.py`
- Create: `hacs.json`
- Create: `README.md`

- [x] **Step 1: Create the custom component directory**

Run: `New-Item -ItemType Directory -Force custom_components/hyundai_bluelink`

- [x] **Step 2: Add a manifest**

The manifest must use domain `hyundai_bluelink`, `config_flow: true`, `iot_class: cloud_polling`, and a custom-component-only `version`.

- [x] **Step 3: Add HACS metadata**

Create `hacs.json` with `"render_readme": true` so HACS can show project documentation.

### Task 2: Pure Data Helpers

**Files:**
- Create: `custom_components/hyundai_bluelink/models.py`
- Test: `tests/test_models.py`

- [x] **Step 1: Write tests for CCS2 telemetry extraction**

Run: `pytest tests/test_models.py -q`

Expected before implementation: fail because `custom_components.hyundai_bluelink.models` does not exist.

- [x] **Step 2: Implement `BluelinkVehicleData` helper methods**

Add path-safe extraction for odometer, range, fuel level, hybrid battery, 12V battery, door/window/tyre states, and location.

- [x] **Step 3: Re-run tests**

Run: `pytest tests/test_models.py -q`

Expected after implementation: pass.

### Task 3: Coordinator and Config Flow

**Files:**
- Create: `custom_components/hyundai_bluelink/config_flow.py`
- Create: `custom_components/hyundai_bluelink/coordinator.py`
- Create: `custom_components/hyundai_bluelink/__init__.py`

- [x] **Step 1: Add UI setup**

Collect email, password, and optional PIN using `ConfigFlow`. Validate credentials by creating an `aiobluelink.AsyncBluelinkClient`, calling async login, and listing vehicles.

- [x] **Step 2: Add reauth**

Implement `async_step_reauth` and `async_step_reauth_confirm` so expired credentials can update the existing config entry.

- [x] **Step 3: Add coordinator**

Use `DataUpdateCoordinator` with `_async_setup` for initial vehicle discovery and `_async_update_data` for batch telemetry refresh.

### Task 4: Entity Platforms

**Files:**
- Create: `custom_components/hyundai_bluelink/entity.py`
- Create: `custom_components/hyundai_bluelink/sensor.py`
- Create: `custom_components/hyundai_bluelink/binary_sensor.py`
- Create: `custom_components/hyundai_bluelink/device_tracker.py`
- Create: `custom_components/hyundai_bluelink/lock.py`
- Create: `custom_components/hyundai_bluelink/button.py`

- [x] **Step 1: Add shared entity base**

Every entity must expose `unique_id` and `device_info` under one vehicle device.

- [x] **Step 2: Add status entities**

Create sensors, binary sensors, and device trackers from coordinator data only.

- [x] **Step 3: Add control entities**

Expose lock/unlock through `LockEntity`; expose start engine, stop engine, horn, lights, windows, and refresh as `ButtonEntity` actions that delegate to the upstream client.

### Task 5: Localization and Services

**Files:**
- Create: `custom_components/hyundai_bluelink/strings.json`
- Create: `custom_components/hyundai_bluelink/translations/en.json`
- Create: `custom_components/hyundai_bluelink/services.yaml`

- [x] **Step 1: Add config-flow strings**

Provide user, reauth, and error labels.

- [x] **Step 2: Add service schema docs**

Document future service actions while the primary action UI is entity based.

### Task 6: Verification

**Files:**
- Existing files from tasks 1-5

- [x] **Step 1: Run parser tests**

Run: `pytest tests/test_models.py -q`

- [x] **Step 2: Compile Python**

Run: `python -m compileall custom_components tests`

- [x] **Step 3: Inspect repository status**

Run: `git status --short`
