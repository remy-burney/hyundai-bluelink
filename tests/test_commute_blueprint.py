"""Regression checks for the optional commute blueprint templates."""

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from jinja2.nativetypes import NativeEnvironment


def test_commute_blueprint_freshness_direction_and_eta():
    """Reject stale/future fixes and require confirmed progress before an ETA."""

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!input", lambda loader, node: loader.construct_scalar(node))
    path = (
        Path(__file__).resolve().parents[1]
        / "blueprints/automation/car_departure_eta.yaml"
    )
    data = yaml.load(path.read_text(), Loader=Loader)
    env = NativeEnvironment()
    now = datetime(2026, 9, 20, 7, tzinfo=UTC)
    stamp = now.timestamp()
    distances = {"zone.work": 1.0, "zone.home": 10.0}
    state = "not_home"
    paused = False
    env.globals.update(
        now=lambda: now,
        timedelta=timedelta,
        states=lambda entity: state,
        distance=lambda car, zone: distances[zone],
        state_attr=lambda entity, attr: (
            paused
            if attr == "polling_paused"
            else stamp
            if attr == "location_updated_at"
            else (100 if attr == "radius" else entity.split(".")[-1].title())
        ),
        as_timestamp=lambda value, default=0: (
            value.timestamp() if isinstance(value, datetime) else value or default
        ),
    )

    def strings(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
        elif isinstance(value, str):
            yield value

    templates = [s for s in strings(data) if "{{" in s or "{%" in s]
    for template in templates:
        env.parse(template)
    context = {
        "car": "device_tracker.car",
        "origin": "zone.work",
        "destination": "zone.home",
        "trigger": {"from_state": "old car"},
        "required_samples": 1,
    }

    def render(template, **extra):
        result = env.from_string(template).render(**(context | extra))
        if isinstance(result, str):
            try:
                return ast.literal_eval(result.strip())
            except (ValueError, SyntaxError):
                return result.strip()
        return result

    freshness = data["conditions"][1]["value_template"]
    assert render(freshness) is True
    paused = True
    assert render(freshness) is False
    paused = False
    stamp -= 181
    assert render(freshness) is False
    stamp = now.timestamp() + 1
    assert render(freshness) is False
    stamp = None
    assert render(freshness) is False
    stamp = now.timestamp()
    abort = data["actions"][1]["repeat"]["sequence"][1]["if"][0]["value_template"]
    assert render(abort) is False
    paused = True
    assert render(abort) is True
    paused = False
    distances["zone.work"] = 0.05
    assert render(abort) is True
    distances["zone.work"] = 1.0
    state = "unavailable"
    assert render(abort) is True
    state = "not_home"
    approach = data["actions"][1]["repeat"]["sequence"][2]["variables"][
        "approach_count"
    ]
    assert (
        render(approach, approach_count=0, previous_distance=10, current_distance=9.7)
        == 1
    )
    assert (
        render(approach, approach_count=1, previous_distance=9.7, current_distance=9.3)
        == 2
    )
    assert (
        render(approach, approach_count=1, previous_distance=9.7, current_distance=9.8)
        == 0
    )
    minutes_template = data["actions"][5]["variables"]["minutes"]
    assert render(minutes_template, routes={}) == 0
    assert (
        render(
            minutes_template,
            routes={"routes": [{"duration": 20.2}, {"duration": 15.1}]},
        )
        == 16
    )
    message = data["actions"][5]["variables"]["commute_message"]
    assert "Estimated arrival" in render(message, minutes=16)
    assert "unavailable" in render(message, minutes=0)
    initial = data["actions"][0]["variables"]
    # The first out-of-zone GPS observation is already an approach sample.
    assert (
        render(initial["approach_count"], initial_distance=10, previous_distance=9.3)
        == 1
    )
    assert (
        render(initial["approach_count"], initial_distance=10, previous_distance=10.3)
        == 0
    )
    confirmed = data["actions"][2]["value_template"]
    assert (
        render(
            confirmed,
            required_samples=1,
            approach_count=1,
            initial_distance=10,
            previous_distance=9.3,
            deadline=now.timestamp() + 1200,
        )
        is True
    )
    assert (
        render(
            confirmed,
            required_samples=2,
            approach_count=1,
            initial_distance=10,
            previous_distance=9.3,
            deadline=now.timestamp() + 1200,
        )
        is False
    )
