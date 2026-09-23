"""Focused-app detection and mode mapping (spec 5.6)."""

import json
import subprocess
from typing import Any

import pytest

from flowd.config import Config, Inject
from flowd.context import AppContext, detect, focused_app_id

SWAY_TREE = {
    "focused": False,
    "nodes": [
        {
            "focused": False,
            "nodes": [
                {"focused": False, "app_id": "firefox", "nodes": [], "floating_nodes": []},
                {"focused": True, "app_id": "foot", "nodes": [], "floating_nodes": []},
            ],
            "floating_nodes": [],
        }
    ],
    "floating_nodes": [],
}


class FakeRun:
    def __init__(self, outputs: dict[str, str | Exception]) -> None:
        self.outputs = outputs
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> Any:
        self.calls.append(argv)
        out = self.outputs.get(argv[0])
        if out is None:
            raise FileNotFoundError(argv[0])
        if isinstance(out, Exception):
            raise out
        return subprocess.CompletedProcess(argv, 0, stdout=out.encode(), stderr=b"")


HYPR_ENV = {"HYPRLAND_INSTANCE_SIGNATURE": "abc", "WAYLAND_DISPLAY": "wayland-1"}


def test_hyprland_reads_the_active_window_class() -> None:
    run = FakeRun({"hyprctl": json.dumps({"class": "kitty", "initialClass": "kitty"})})
    assert focused_app_id(env=HYPR_ENV, runner=run) == "kitty"
    assert run.calls == [["hyprctl", "activewindow", "-j"]]


def test_hyprland_with_nothing_focused_is_none() -> None:
    assert focused_app_id(env=HYPR_ENV, runner=FakeRun({"hyprctl": "{}"})) is None


def test_sway_finds_the_focused_node() -> None:
    run = FakeRun({"swaymsg": json.dumps(SWAY_TREE)})
    env = {"SWAYSOCK": "/run/sway.sock", "WAYLAND_DISPLAY": "wayland-1"}
    assert focused_app_id(env=env, runner=run) == "foot"


def test_sway_xwayland_window_uses_its_class() -> None:
    tree = {
        "focused": False,
        "nodes": [
            {
                "focused": True,
                "app_id": None,
                "window_properties": {"class": "Slack"},
                "nodes": [],
                "floating_nodes": [],
            }
        ],
        "floating_nodes": [],
    }
    env = {"SWAYSOCK": "/run/sway.sock"}
    assert focused_app_id(env=env, runner=FakeRun({"swaymsg": json.dumps(tree)})) == "Slack"


def test_x11_uses_xdotool() -> None:
    run = FakeRun({"xdotool": "Thunderbird\n"})
    assert focused_app_id(env={"DISPLAY": ":0"}, runner=run) == "Thunderbird"
    assert run.calls == [["xdotool", "getactivewindow", "getwindowclassname"]]


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("hyprctl"),
        subprocess.CalledProcessError(1, "hyprctl"),
        subprocess.TimeoutExpired("hyprctl", 0.5),
    ],
)
def test_a_failing_tool_is_none_never_an_error(failure: Exception) -> None:
    assert focused_app_id(env=HYPR_ENV, runner=FakeRun({"hyprctl": failure})) is None


def test_garbage_output_is_none() -> None:
    assert focused_app_id(env=HYPR_ENV, runner=FakeRun({"hyprctl": "not json"})) is None


def test_no_known_session_is_none() -> None:
    run = FakeRun({})
    assert focused_app_id(env={}, runner=run) is None
    assert run.calls == []


def test_detect_maps_the_mode_and_flags_terminals() -> None:
    run = FakeRun({"hyprctl": json.dumps({"class": "kitty"})})
    cfg = Config(modes=(("kitty", "code"),))
    assert detect(cfg, env=HYPR_ENV, runner=run) == AppContext("kitty", "code", True)


def test_detect_matches_app_ids_case_insensitively() -> None:
    # X11 reports "Thunderbird"; the spec's [modes] example says "thunderbird".
    run = FakeRun({"xdotool": "Thunderbird\n"})
    ctx = detect(Config(), env={"DISPLAY": ":0"}, runner=run)
    assert ctx.mode == "email"
    run = FakeRun({"xdotool": "alacritty\n"})
    cfg = Config(inject=Inject(terminal_apps=("Alacritty",)))
    assert detect(cfg, env={"DISPLAY": ":0"}, runner=run).is_terminal


def test_detect_unknown_app_is_default_and_not_terminal() -> None:
    ctx = detect(Config(), env={}, runner=FakeRun({}))
    assert ctx == AppContext(None, "default", False)


def test_a_terminal_with_no_mapping_gets_code_mode() -> None:
    # spec 7.3: code mode is "chosen for terminals, IDEs, code editors".
    run = FakeRun({"hyprctl": json.dumps({"class": "kitty"})})
    assert detect(Config(), env=HYPR_ENV, runner=run) == AppContext("kitty", "code", True)


def test_an_explicit_mapping_wins_over_the_terminal_default() -> None:
    run = FakeRun({"hyprctl": json.dumps({"class": "kitty"})})
    cfg = Config(modes=(("kitty", "chat"),))
    assert detect(cfg, env=HYPR_ENV, runner=run).mode == "chat"
