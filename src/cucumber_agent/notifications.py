"""Small notification helpers for agent-facing UI events."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

_FALSE_VALUES = {"0", "false", "no", "off", "aus"}
_TRUE_VALUES = {"1", "true", "yes", "on", "ja"}


def sound_enabled_from_env(default: bool) -> bool:
    """Return notification sound preference with env-var override."""
    raw = os.environ.get("CUCUMBER_NOTIFY_SOUND")
    if raw is None:
        return default

    value = raw.strip().lower()
    if value in _FALSE_VALUES:
        return False
    if value in _TRUE_VALUES:
        return True
    return default


def play_agent_message_sound(enabled: bool = True) -> bool:
    """Play a short sound when a visible agent message arrives.

    macOS gets a native system beep. Other platforms use the terminal bell,
    which is harmless if the terminal has audible bells disabled.
    """
    if not sound_enabled_from_env(enabled):
        return False

    if sys.platform == "darwin" and shutil.which("osascript"):
        try:
            subprocess.Popen(
                ["osascript", "-e", "beep"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            pass

    try:
        sys.stdout.write("\a")
        sys.stdout.flush()
        return True
    except Exception:
        return False
