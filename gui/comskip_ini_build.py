"""Materialize a per-run Comskip.ini from the bundled template + job overrides."""

from __future__ import annotations

import re
from pathlib import Path

from comskip_settings import ComskipSettings
from paths import comskip_ini

# key=value with optional trailing whitespace / comment
_KEY_LINE = re.compile(r"^([A-Za-z0-9_]+)=(.*)$")


def apply_ini_overrides(template_text: str, overrides: dict[str, str]) -> str:
    """Replace first occurrence of each key=...; append missing keys. Preserve comments."""
    remaining = dict(overrides)
    out_lines: list[str] = []
    for raw in template_text.splitlines(keepends=True):
        ends_crlf = raw.endswith("\r\n")
        ends_lf = raw.endswith("\n") and not ends_crlf
        line = raw.rstrip("\r\n")
        newline = "\r\n" if ends_crlf else ("\n" if ends_lf else "")

        if ";" in line:
            code, comment = line.split(";", 1)
            has_comment = True
        else:
            code, comment = line, ""
            has_comment = False

        m = _KEY_LINE.match(code.rstrip())
        if m and m.group(1) in remaining:
            key = m.group(1)
            val = remaining.pop(key)
            if has_comment:
                out_lines.append(f"{key}={val}\t\t;{comment}{newline}")
            else:
                out_lines.append(f"{key}={val}{newline}")
        else:
            out_lines.append(raw if (ends_crlf or ends_lf) else (raw + "\n"))

    if remaining:
        if out_lines and not out_lines[-1].endswith("\n"):
            out_lines[-1] = out_lines[-1] + "\n"
        out_lines.append("\n; Per-job overrides (appended)\n")
        for key, val in remaining.items():
            out_lines.append(f"{key}={val}\n")
    return "".join(out_lines)


def materialize_comskip_ini(
    settings: ComskipSettings,
    dest: Path,
    *,
    template_path: Path | None = None,
) -> Path:
    """Write dest ini from template + settings overrides; return dest."""
    src = template_path or comskip_ini()
    text = src.read_text(encoding="utf-8", errors="replace")
    merged = apply_ini_overrides(text, settings.ini_overrides())
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(merged, encoding="utf-8", newline="\n")
    return dest
