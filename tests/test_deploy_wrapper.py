"""deploy/mt5-mcp, the in-container wrapper, run against a fake `wine`."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

WRAPPER = Path(__file__).parent.parent / "deploy" / "mt5-mcp"

pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None or os.geteuid() == 0,
    reason="bash wrapper for the Linux image; as root it re-execs through s6-setuidgid",
)

FAKE_WINE = """#!/bin/bash
printf '%s\\0' "$@" > "$FAKE_DIR/args"
printf '%s|%s|%s' "$WINEPREFIX" "$WINEDEBUG" "$DISPLAY" > "$FAKE_DIR/env"
printf 'out\\r\\n'
printf 'err\\r\\n' >&2
exit "${FAKE_RC:-0}"
"""


@pytest.fixture
def run(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "wine").write_text(FAKE_WINE)
    (bin_dir / "wine").chmod(0o755)

    def _run(args, rc=0):
        env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_DIR": str(tmp_path), "FAKE_RC": str(rc)}
        p = subprocess.run(["bash", str(WRAPPER), *args], env=env, capture_output=True, text=True)
        argv = (tmp_path / "args").read_text().split("\0")[:-1]
        prefix, debug, display = (tmp_path / "env").read_text().split("|")
        return SimpleNamespace(args=argv, env={"WINEPREFIX": prefix, "WINEDEBUG": debug, "DISPLAY": display},
                               stdout=p.stdout, stderr=p.stderr, returncode=p.returncode)

    return _run


def test_translates_absolute_paths_only(run):
    r = run(["backtest", "/home/v/w/src/My EA.ex5", "--out=/home/v/w/out", "--symbol", "EURUSD.z", "rel/x.set"])
    assert r.args == ["C:\\Python311\\python.exe", "-m", "mt5_mcp", "backtest",
                      "Z:\\home\\v\\w\\src\\My EA.ex5", "--out=Z:\\home\\v\\w\\out", "--symbol", "EURUSD.z",
                      "rel/x.set"]


def test_sets_wine_env(run):
    assert run(["--version"]).env == {"WINEPREFIX": "/config/.wine", "WINEDEBUG": "-all", "DISPLAY": ":1"}


def test_strips_cr_and_keeps_streams(run):
    r = run(["x"])
    assert (r.stdout, r.stderr) == ("out\n", "err\n")


@pytest.mark.parametrize("rc", [0, 1, 2])
def test_keeps_exit_code(run, rc):
    assert run(["x"], rc=rc).returncode == rc
