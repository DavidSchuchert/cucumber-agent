"""Tests for notification helpers."""

from __future__ import annotations

import io

from cucumber_agent.notifications import play_agent_message_sound, sound_enabled_from_env


def test_sound_enabled_from_env_respects_false_values(monkeypatch):
    monkeypatch.setenv("CUCUMBER_NOTIFY_SOUND", "0")

    assert sound_enabled_from_env(True) is False


def test_sound_enabled_from_env_respects_true_values(monkeypatch):
    monkeypatch.setenv("CUCUMBER_NOTIFY_SOUND", "ja")

    assert sound_enabled_from_env(False) is True


def test_play_agent_message_sound_returns_false_when_disabled(monkeypatch):
    monkeypatch.delenv("CUCUMBER_NOTIFY_SOUND", raising=False)

    assert play_agent_message_sound(enabled=False) is False


def test_play_agent_message_sound_falls_back_to_terminal_bell(monkeypatch):
    stream = io.StringIO()
    monkeypatch.delenv("CUCUMBER_NOTIFY_SOUND", raising=False)
    monkeypatch.setattr("cucumber_agent.notifications.sys.platform", "linux")
    monkeypatch.setattr("cucumber_agent.notifications.sys.stdout", stream)

    assert play_agent_message_sound(enabled=True) is True
    assert stream.getvalue() == "\a"
