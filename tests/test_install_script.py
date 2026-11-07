"""scripts/install.sh --dry-run: the units it would write for this machine."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "install.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def dry_run(tmp_path: Path, *, script: Path = SCRIPT, **env: str) -> str:
    """Run the installer with a throwaway HOME, so nothing real is touched."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        **env,
    }
    result = subprocess.run(
        ["bash", str(script), "--dry-run"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout


def test_the_daemon_unit_runs_flowd_from_this_checkout(tmp_path: Path) -> None:
    """The shipped ExecStart is a placeholder; the installer points it here."""
    out = dry_run(tmp_path)
    assert f"ExecStart={REPO}/.venv/bin/flowd" in out


def test_the_model_path_follows_xdg_data_home(tmp_path: Path) -> None:
    """systemd cannot read XDG_DATA_HOME, so the installer writes the path out."""
    out = dry_run(tmp_path)
    model = tmp_path / "data" / "flowd" / "models" / "sotto-cleanup-lfm25-350m-q4_k_m.gguf"
    assert f"Environment=FLOWD_MODEL={model}" in out


def test_llama_server_threads_can_be_overridden(tmp_path: Path) -> None:
    out = dry_run(tmp_path, FLOWD_LLM_THREADS="3")
    assert "llama-server threads: 3" in out
    assert "--port 8177 -t 3" in out


def test_a_dry_run_changes_nothing(tmp_path: Path) -> None:
    dry_run(tmp_path)
    assert not (tmp_path / "config" / "systemd").exists()
    assert not (tmp_path / "home" / ".local" / "bin").exists()


def test_an_unknown_option_is_refused(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--bogus"], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 2
    assert "unknown option" in result.stderr


def test_the_ui_build_is_planned_or_explained(tmp_path: Path) -> None:
    out = dry_run(tmp_path)
    assert "would run: cmake -S" in out or "flowd-ui not built" in out


def test_skipping_the_ui_build_is_not_fatal(tmp_path: Path) -> None:
    out = dry_run(tmp_path, FLOWD_UI_BUILD="0")
    assert "flowd-ui not built" in out
    assert "Writing systemd units" in out


def fake_path(tmp_path: Path, *tools: str) -> str:
    """Only expose the requested tools; never depend on the host's desktop."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("bash", "dirname", "grep", "sort", "wc", "sed", "cat"):
        source = shutil.which(name)
        assert source is not None
        (bindir / name).symlink_to(source)
    commands = {
        "ldconfig": "printf 'libportaudio.so.2\\n'",
        "lscpu": "printf '# Core\\n0\\n1\\n2\\n3\\n'",
        **{name: "exit 0" for name in tools},
    }
    for name, body in commands.items():
        target = bindir / name
        target.write_text("#!/bin/sh\n" + body + "\n")
        target.chmod(0o755)
    return str(bindir)


def test_missing_ubuntu_packages_use_apt_names(tmp_path: Path) -> None:
    """Ubuntu must not be told to install Arch's portaudio with pacman."""
    path = fake_path(tmp_path, "uv", "curl", "pw-cli", "llama-server", "apt-get")
    # Model a machine with no PortAudio library either.
    (Path(path) / "ldconfig").write_text("#!/bin/sh\nexit 0\n")
    out = dry_run(tmp_path, PATH=path, WAYLAND_DISPLAY="wayland-0")
    assert "sudo apt install libportaudio2 wl-clipboard wtype" in out
    assert "pacman" not in out


@pytest.mark.parametrize("desktop", ["GNOME", "ubuntu:GNOME", "Ubuntu:gNoMe"])
def test_gnome_wayland_requires_ydotool_instead_of_wtype(tmp_path: Path, desktop: str) -> None:
    """Mutter rejects wtype's virtual keyboard protocol even when installed."""
    path = fake_path(tmp_path, "uv", "curl", "pw-cli", "llama-server", "wtype", "apt-get")
    out = dry_run(tmp_path, PATH=path, WAYLAND_DISPLAY="wayland-0", XDG_CURRENT_DESKTOP=desktop)
    assert "missing: ydotool" in out
    assert "sudo apt install ydotool" in out


# The bare command lists of Ubuntu 24.04's 0.1.8 and 26.04's 1.0.4 packages.
YDOTOOL_0X = "printf 'Usage: ydotool <cmd> <args>\\nAvailable commands:\\n  type\\n  recorder\\n'"
YDOTOOL_1X = (
    "printf 'Usage: ydotool <cmd> <args>\\nAvailable commands:\\n  click\\n  type\\n  bakers\\n'"
)


def fake_tool(path: str, name: str, body: str) -> None:
    target = Path(path) / name
    target.write_text("#!/bin/sh\n" + body + "\n")
    target.chmod(0o755)


def test_ydotool_0x_is_reported_with_the_upstream_pointer(tmp_path: Path) -> None:
    """Ubuntu 24.04 packages 0.1.8: no ydotoold, no -d/-H, and exit 0 anyway."""
    path = fake_path(tmp_path, "uv", "curl", "pw-cli", "llama-server", "apt-get")
    fake_tool(path, "ydotool", YDOTOOL_0X)
    out = dry_run(tmp_path, PATH=path, WAYLAND_DISPLAY="wayland-0", XDG_CURRENT_DESKTOP="GNOME")
    assert "older than 1.0" in out
    assert "github.com/ReimuNotMoe/ydotool" in out


def test_ydotool_1x_is_accepted(tmp_path: Path) -> None:
    path = fake_path(tmp_path, "uv", "curl", "pw-cli", "llama-server", "apt-get")
    fake_tool(path, "ydotool", YDOTOOL_1X)
    out = dry_run(tmp_path, PATH=path, WAYLAND_DISPLAY="wayland-0", XDG_CURRENT_DESKTOP="GNOME")
    assert "older than 1.0" not in out


def test_gnome_with_xwayland_needs_xclip(tmp_path: Path) -> None:
    path = fake_path(tmp_path, "uv", "curl", "pw-cli", "llama-server", "ydotool", "apt-get")
    out = dry_run(
        tmp_path, PATH=path, WAYLAND_DISPLAY="wayland-0", DISPLAY=":0", XDG_CURRENT_DESKTOP="GNOME"
    )
    assert "missing: xclip" in out
    assert "sudo apt install xclip" in out


def test_gnome_wayland_can_install_with_only_ydotool(tmp_path: Path) -> None:
    path = fake_path(tmp_path, "uv", "curl", "pw-cli", "llama-server", "ydotool", "apt-get")
    out = dry_run(tmp_path, PATH=path, WAYLAND_DISPLAY="wayland-0", XDG_CURRENT_DESKTOP="GNOME")
    assert "all present" in out
    assert "flowd-ui not built (GNOME Wayland" in out
    assert "uinput" in out


def test_ubuntu_does_not_offer_nonportable_uv_or_llama_packages(tmp_path: Path) -> None:
    """Older Ubuntu releases do not package the cleanup server or uv."""
    path = fake_path(tmp_path, "curl", "pw-cli", "xclip", "xdotool", "apt-get")
    out = dry_run(tmp_path, PATH=path)
    assert "Install uv:" in out
    assert "Install llama-server:" in out
    assert "sudo apt install uv" not in out
    assert "pacman" not in out


def test_ubuntu_ui_hint_uses_development_package_names(tmp_path: Path) -> None:
    path = fake_path(
        tmp_path, "uv", "curl", "pw-cli", "llama-server", "xclip", "xdotool", "apt-get"
    )
    out = dry_run(tmp_path, PATH=path)
    assert "sudo apt install cmake g++ pkg-config libgtkmm-4.0-dev libgtk4-layer-shell-dev" in out


def test_new_virtualenv_requests_a_supported_python(tmp_path: Path) -> None:
    """Ubuntu 22.04's system Python 3.10 does not satisfy requires-python."""
    repo = tmp_path / "repo"
    for directory in ("scripts", "systemd"):
        shutil.copytree(REPO / directory, repo / directory)
    out = dry_run(tmp_path, script=repo / "scripts" / "install.sh")
    assert "would run: uv venv --python >=3.11" in out


def test_cram_is_dropped_for_a_llama_server_without_it(tmp_path: Path) -> None:
    """Ubuntu 25.10's llama.cpp predates -cram and would refuse to start."""
    path = fake_path(tmp_path, "uv", "curl", "pw-cli", "xclip", "xdotool")
    (Path(path) / "llama-server").write_text('#!/bin/sh\necho "-c, --ctx-size N"\n')
    (Path(path) / "llama-server").chmod(0o755)
    out = dry_run(tmp_path, PATH=path)
    assert f"ExecStart={path}/llama-server " in out
    assert "-cram" not in out


def test_cram_is_kept_for_a_llama_server_with_it(tmp_path: Path) -> None:
    path = fake_path(tmp_path, "uv", "curl", "pw-cli", "xclip", "xdotool")
    (Path(path) / "llama-server").write_text('#!/bin/sh\necho "-cram, --cache-ram N"\n')
    (Path(path) / "llama-server").chmod(0o755)
    out = dry_run(tmp_path, PATH=path)
    assert "-cram 0" in out


def test_a_llama_server_built_into_local_bin_is_found(tmp_path: Path) -> None:
    """Ubuntu 24.04 has no llama.cpp package; the README builds it into ~/.local/bin."""
    path = fake_path(tmp_path, "uv", "curl", "pw-cli", "xclip", "xdotool")
    local_bin = tmp_path / "home" / ".local" / "bin"
    local_bin.mkdir(parents=True)
    (local_bin / "llama-server").write_text('#!/bin/sh\necho "--cache-ram N"\n')
    (local_bin / "llama-server").chmod(0o755)
    out = dry_run(tmp_path, PATH=path)
    assert "all present" in out
    assert f"ExecStart={local_bin}/llama-server " in out


@pytest.mark.parametrize("desktop", ["GNOME", "ubuntu:GNOME", "Ubuntu:gNoMe"])
def test_gnome_with_xwayland_builds_the_focus_safe_preview(tmp_path: Path, desktop: str) -> None:
    """GNOME can use the X11 UI when its XWayland display is available."""
    path = fake_path(
        tmp_path,
        "uv",
        "curl",
        "pw-cli",
        "llama-server",
        "ydotool",
        "apt-get",
        "cmake",
        "g++",
        "pkg-config",
    )
    out = dry_run(
        tmp_path,
        PATH=path,
        WAYLAND_DISPLAY="wayland-0",
        DISPLAY=":0",
        XDG_CURRENT_DESKTOP=desktop,
    )
    assert "would run: cmake -S" in out
    assert "flowd-ui not built" not in out


def test_gnome_xwayland_still_respects_the_explicit_ui_skip(tmp_path: Path) -> None:
    path = fake_path(
        tmp_path,
        "uv",
        "curl",
        "pw-cli",
        "llama-server",
        "ydotool",
        "apt-get",
        "cmake",
        "g++",
        "pkg-config",
    )
    out = dry_run(
        tmp_path,
        PATH=path,
        WAYLAND_DISPLAY="wayland-0",
        DISPLAY=":0",
        XDG_CURRENT_DESKTOP="GNOME",
        FLOWD_UI_BUILD="0",
    )
    assert "would run: cmake -S" not in out
    assert "flowd-ui not built" in out
