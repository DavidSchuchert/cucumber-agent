"""Datetime tool — returns current date/time and converts between timezones."""

from __future__ import annotations

from datetime import datetime, timezone

from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry

# Compact mapping of common timezone abbreviations to UTC offsets (hours).
# For full IANA timezone support the user would need 'zoneinfo' (stdlib ≥ 3.9).
_TZ_OFFSETS: dict[str, float] = {
    "UTC": 0,
    "GMT": 0,
    "CET": 1,  # Central European Time
    "CEST": 2,  # Central European Summer Time
    "EET": 2,  # Eastern European Time
    "EEST": 3,  # Eastern European Summer Time
    "MSK": 3,  # Moscow Standard Time
    "IST": 5.5,  # India Standard Time
    "CST": 8,  # China Standard Time
    "JST": 9,  # Japan Standard Time
    "AEST": 10,  # Australian Eastern Standard Time
    "AEDT": 11,  # Australian Eastern Daylight Time
    "NZST": 12,  # New Zealand Standard Time
    "EST": -5,  # US Eastern Standard Time
    "EDT": -4,  # US Eastern Daylight Time
    "CST_US": -6,  # US Central Standard Time
    "CDT": -5,  # US Central Daylight Time
    "MST": -7,  # US Mountain Standard Time
    "MDT": -6,  # US Mountain Daylight Time
    "PST": -8,  # US Pacific Standard Time
    "PDT": -7,  # US Pacific Daylight Time
    "AKST": -9,  # Alaska Standard Time
    "HST": -10,  # Hawaii Standard Time
    "BRT": -3,  # Brasilia Time
    "ART": -3,  # Argentina Time
    "WET": 0,  # Western European Time
    "WEST": 1,  # Western European Summer Time
}


def _parse_tz(name: str) -> timezone | None:
    """Return a timezone object for a known abbreviation, or None."""
    key = name.strip().upper()
    if key in _TZ_OFFSETS:
        from datetime import timedelta

        offset_hours = _TZ_OFFSETS[key]
        return timezone(timedelta(hours=offset_hours), name=key)
    # Try IANA via zoneinfo (Python 3.9+)
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            zi = ZoneInfo(name)
            # zoneinfo doesn't expose a fixed-offset timezone, but datetime.now(zi) works
            return zi  # type: ignore[return-value]
        except ZoneInfoNotFoundError:
            return None
    except ImportError:
        return None


class DatetimeTool(BaseTool):
    """Returns current date/time and optionally converts between timezones."""

    name = "datetime"
    description = (
        "Returns the current date and time. "
        "Can optionally return the time in a specific timezone "
        "(e.g. 'UTC', 'CET', 'EST', 'JST', or an IANA name like 'Europe/Berlin'). "
        "Supported abbreviations: UTC, GMT, CET, CEST, EET, MSK, IST, CST, JST, "
        "AEST, NZST, EST, EDT, PST, PDT, BRT, ART, and more."
    )
    parameters = {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": (
                    "Timezone name or abbreviation (e.g. 'UTC', 'CET', 'Europe/Berlin'). "
                    "Omit to use the local system timezone."
                ),
            },
            "format": {
                "type": "string",
                "description": (
                    "strftime format string (e.g. '%Y-%m-%d %H:%M:%S'). "
                    "Defaults to a human-readable ISO-8601 format."
                ),
            },
        },
        "required": [],
    }
    auto_approve = True

    async def execute(
        self,
        timezone: str | None = None,
        format: str | None = None,
    ) -> ToolResult:
        fmt = format or "%Y-%m-%d %H:%M:%S %Z"

        try:
            if timezone:
                tz_obj = _parse_tz(timezone)
                if tz_obj is None:
                    return ToolResult(
                        success=False,
                        output="",
                        error=(
                            f"Unknown timezone: '{timezone}'. "
                            "Use a standard abbreviation (UTC, CET, EST, JST, …) "
                            "or an IANA name (Europe/Berlin, America/New_York, …)."
                        ),
                    )
                now = datetime.now(tz=tz_obj)
            else:
                # Local time with UTC offset shown
                now = datetime.now().astimezone()

            formatted = now.strftime(fmt)
            # Build an informative output
            iso = now.isoformat()
            output_lines = [
                f"Aktuelles Datum/Uhrzeit: {formatted}",
                f"ISO-8601: {iso}",
            ]
            if timezone:
                output_lines.append(f"Zeitzone: {timezone}")

            return ToolResult(success=True, output="\n".join(output_lines))

        except Exception as exc:
            return ToolResult(success=False, output="", error=f"Datetime error: {exc}")


ToolRegistry.register(DatetimeTool())
