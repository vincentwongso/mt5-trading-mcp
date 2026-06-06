from __future__ import annotations

from unittest.mock import patch

import pytest

from mt5_mcp.__main__ import main


def test_serve_default_transport_is_stdio(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))  # stop Windows wandering off
    captured = {}
    def fake_run(mcp, *, transport, config):
        captured["transport"] = transport
    with patch("mt5_mcp.transport.run", side_effect=fake_run):
        rc = main(["serve"])
    assert rc == 0
    assert captured["transport"] == "stdio"


def test_serve_http_transport_routes_to_http(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    captured = {}
    def fake_run(mcp, *, transport, config):
        captured["transport"] = transport
    with patch("mt5_mcp.transport.run", side_effect=fake_run):
        rc = main(["serve", "--transport", "http"])
    assert rc == 0
    assert captured["transport"] == "http"


def test_serve_invalid_transport_returns_nonzero(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    rc = main(["serve", "--transport", "ftp"])
    assert rc != 0


def test_serve_eager_connect_flag_sets_config(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    captured = {}
    def fake_run(mcp, *, transport, config):
        captured["eager"] = config.mt5.eager_connect
    with patch("mt5_mcp.transport.run", side_effect=fake_run):
        rc = main(["serve", "--eager-connect"])
    assert rc == 0
    assert captured["eager"] is True


def test_serve_without_eager_connect_flag_defaults_false(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    captured = {}
    def fake_run(mcp, *, transport, config):
        captured["eager"] = config.mt5.eager_connect
    with patch("mt5_mcp.transport.run", side_effect=fake_run):
        rc = main(["serve"])
    assert rc == 0
    assert captured["eager"] is False
