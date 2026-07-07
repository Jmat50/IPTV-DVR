"""Run Comskip commercial detection on finished MPEG-TS recordings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from console_guard import GUARD_COMSKIP
from paths import comskip_exe, comskip_ini
from recorder import run_tool


@dataclass(frozen=True)
class ComskipRunResult:
    ok: bool
    exit_code: int
    edl_path: Path | None
    txt_path: Path | None


def comskip_sidecar_edl(input_ts: Path) -> Path:
    return input_ts.with_suffix(".edl")


def comskip_sidecar_txt(input_ts: Path) -> Path:
    return input_ts.with_suffix(".txt")


def build_comskip_argv(
    exe: Path,
    input_ts: Path,
    *,
    ini_path: Path,
) -> list[str]:
    return [
        str(exe),
        f"--ini={ini_path}",
        "-t",
        str(input_ts),
    ]


def try_run_comskip(
    input_ts: Path,
    *,
    ini_path: Path | None = None,
    log_file: Path | None = None,
    work_dir: Path | None = None,
) -> ComskipRunResult:
    """Run Comskip on a finished .ts file; sidecars are written beside input_ts."""
    exe = comskip_exe()
    ini = ini_path or comskip_ini()
    if not exe.is_file():
        return ComskipRunResult(False, 127, None, None)
    if not ini.is_file():
        return ComskipRunResult(False, 127, None, None)

    argv = build_comskip_argv(exe, input_ts, ini_path=ini)
    cwd = work_dir or input_ts.parent
    code = run_tool(
        argv,
        log_file=log_file,
        cwd=cwd,
        console_guard=GUARD_COMSKIP,
    )
    edl = comskip_sidecar_edl(input_ts)
    txt = comskip_sidecar_txt(input_ts)
    edl_ok = edl.is_file() and edl.stat().st_size > 0
    txt_ok = txt.is_file() and txt.stat().st_size > 0
    ok = code == 0 and (edl_ok or txt_ok)
    return ComskipRunResult(
        ok=ok,
        exit_code=code,
        edl_path=edl if edl_ok else None,
        txt_path=txt if txt_ok else None,
    )
