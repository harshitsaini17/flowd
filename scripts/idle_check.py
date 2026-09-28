#!/usr/bin/env python3
"""Measure idle memory and CPU against spec 10.1.

Sums anonymous memory (ADR 0006) and RSS over flowd, its overlay and
llama-server, then samples their CPU time for `--seconds` (spec 10.1: 60 s).
With `--soak HOURS` it repeats the check every `--every` minutes and reports
growth and PID changes, which is the 24 h leak and restart check. Also verifies
that flowd holds no PipeWire client while idle (ADR 0015).

Run it while flowd is idle. Reads /proc only; it never talks to the daemon.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RAM_BUDGET_MB = 1600.0  # ADR 0011
CPU_BUDGET_PCT = 1.0
PW_DUMP_TIMEOUT_S = 10.0  # stops a hung PipeWire from hanging the check
#: How each process is recognised: its executable's name, then a script
#: argument. Matching on argv[0] keeps out shells and editors whose command
#: line merely mentions flowd.
PATTERNS = {
    "flowd": ("python", "/bin/flowd"),
    "overlay": ("python", "flowd_overlay.py"),
    "llama-server": ("llama-server", ""),
}


@dataclass(frozen=True, slots=True)
class Proc:
    name: str
    pid: int
    anon_mb: float
    rss_mb: float
    cpu_ticks: int


def _cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except OSError:
        return ""


def _status_kb(pid: int, key: str) -> float:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith(key + ":"):
            return float(line.split()[1])
    return 0.0


def _cpu_ticks(pid: int) -> int:
    # Fields after the command name, which may itself contain spaces.
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return int(fields[11]) + int(fields[12])  # utime + stime


def find() -> list[Proc]:
    me = os.getpid()
    found: list[Proc] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        pid = int(entry.name)
        argv = _cmdline(pid).split()
        if len(argv) < 1:
            continue
        exe, script = os.path.basename(argv[0]), argv[1] if len(argv) > 1 else ""
        for name, (exe_prefix, script_suffix) in PATTERNS.items():
            if exe.startswith(exe_prefix) and script.endswith(script_suffix):
                with contextlib.suppress(OSError):  # exited while we looked
                    found.append(
                        Proc(
                            name,
                            pid,
                            _status_kb(pid, "RssAnon") / 1024,
                            _status_kb(pid, "VmRSS") / 1024,
                            _cpu_ticks(pid),
                        )
                    )
                break
    return found


def check(seconds: float) -> tuple[list[Proc], float, float, float]:
    """(processes, anon MB, RSS MB, CPU % of one core) over `seconds`."""
    before = find()
    t0 = time.monotonic()
    time.sleep(seconds)
    elapsed = time.monotonic() - t0
    after = {p.pid: p for p in find()}
    ticks = sum(after[p.pid].cpu_ticks - p.cpu_ticks for p in before if p.pid in after)
    cpu_pct = 100.0 * ticks / os.sysconf("SC_CLK_TCK") / elapsed
    procs = list(after.values())
    return procs, sum(p.anon_mb for p in procs), sum(p.rss_mb for p in procs), cpu_pct


def flowd_clients(dump: list[dict[str, Any]], pids: set[int]) -> list[str]:
    """PipeWire clients owned by `pids`, from `pw-dump` output (ADR 0015).

    An idle flowd should own none: not a capture stream, and not the client
    that `Pa_Initialize` registers even without one.
    """
    found = []
    for obj in dump:
        if not str(obj.get("type", "")).endswith(":Client"):
            continue
        props = (obj.get("info") or {}).get("props") or {}
        pid = props.get("application.process.id")
        if pid in pids:
            found.append(f"{props.get('client.api', '?')} client {obj['id']} (pid {pid})")
    return found


def mic_clients(procs: list[Proc]) -> list[str] | str | None:
    """flowd's PipeWire clients now, a failure reason, or None if pw-dump is missing."""
    if shutil.which("pw-dump") is None:
        return None
    try:
        out = subprocess.run(
            ["pw-dump"], capture_output=True, text=True, check=True, timeout=PW_DUMP_TIMEOUT_S
        )
        return flowd_clients(json.loads(out.stdout), {p.pid for p in procs})
    except subprocess.CalledProcessError as e:
        return f"pw-dump failed: {e.stderr or 'exit code ' + str(e.returncode)}"
    except subprocess.TimeoutExpired:
        return "pw-dump failed: timeout"
    except json.JSONDecodeError as e:
        return f"pw-dump failed: invalid JSON: {e.msg}"


def report(seconds: float) -> bool:
    procs, anon, rss, cpu = check(seconds)
    for p in sorted(procs, key=lambda p: p.name):
        print(f"  {p.name:<13} pid {p.pid:<8} anon {p.anon_mb:7.1f} MB  rss {p.rss_mb:7.1f} MB")
    clients = mic_clients(procs)
    if clients is None:
        print("  audio: pw-dump not found, PipeWire clients not checked")
        audio_ok = True
    elif isinstance(clients, str):
        print(f"  audio: {clients}")
        audio_ok = False
    else:
        print("  audio: " + (", ".join(clients) if clients else "no PipeWire clients"))
        audio_ok = not clients
    ok = anon <= RAM_BUDGET_MB and cpu < CPU_BUDGET_PCT and audio_ok
    print(
        f"  total anon {anon:.1f} MB (budget {RAM_BUDGET_MB:.0f}), rss {rss:.1f} MB, "
        f"cpu {cpu:.2f}% over {seconds:.0f} s (budget < {CPU_BUDGET_PCT:.0f}%) -> "
        + ("PASS" if ok else "FAIL")
    )
    return ok


def soak(hours: float, every_min: float, seconds: float) -> bool:
    start = {p.name: p for p in find()}
    first_anon = sum(p.anon_mb for p in start.values())
    deadline = time.monotonic() + hours * 3600
    ok = True
    while True:
        procs, anon, _, cpu = check(seconds)
        now = {p.name: p.pid for p in procs}
        restarted = [n for n, p in start.items() if now.get(n) != p.pid]
        print(
            f"{time.strftime('%F %T')} anon {anon:.1f} MB ({anon - first_anon:+.1f}) "
            f"cpu {cpu:.2f}%" + (f" RESTARTED {restarted}" if restarted else ""),
            flush=True,
        )
        ok &= not restarted and anon <= RAM_BUDGET_MB and cpu < CPU_BUDGET_PCT
        if time.monotonic() >= deadline:
            return ok
        time.sleep(max(0.0, every_min * 60 - seconds))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--soak", type=float, metavar="HOURS")
    parser.add_argument("--every", type=float, default=30.0, metavar="MINUTES")
    args = parser.parse_args()
    if not find():
        print("no flowd or llama-server process found", file=sys.stderr)
        return 1
    if args.soak:
        return 0 if soak(args.soak, args.every, args.seconds) else 1
    return 0 if report(args.seconds) else 1


if __name__ == "__main__":
    sys.exit(main())
