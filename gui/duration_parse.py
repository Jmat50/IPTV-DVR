"""Parse duration strings like 90m, 1h30m, 3600 (seconds)."""

from __future__ import annotations


def parse_duration(s: str) -> int:
    """Return seconds as int."""
    s = s.strip().lower()
    if not s:
        raise ValueError("empty duration")
    if s.isdigit():
        n = int(s)
        if n <= 0:
            raise ValueError("duration must be positive")
        return n
    total = 0
    rem = s
    while rem:
        i = 0
        while i < len(rem) and rem[i].isdigit():
            i += 1
        if i == 0:
            raise ValueError(f"invalid duration {s!r}")
        n = int(rem[:i])
        if i >= len(rem):
            raise ValueError(f"missing unit in {s!r}")
        unit = rem[i]
        rem = rem[i + 1 :].strip()
        if unit == "h":
            total += n * 3600
        elif unit == "m":
            total += n * 60
        elif unit == "s":
            total += n
        else:
            raise ValueError(f"unknown unit {unit!r}")
    if total <= 0:
        raise ValueError("duration must be positive")
    return total
