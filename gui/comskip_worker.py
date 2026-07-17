"""Run Comskip commercial detection on finished MPEG-TS recordings."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from console_guard import GUARD_COMSKIP
from paths import comskip_artifact_dir, comskip_exe, comskip_ini
from recorder import run_tool


@dataclass(frozen=True)
class ComskipRunResult:
    ok: bool
    exit_code: int
    edl_path: Path | None
    txt_path: Path | None


def comskip_sidecar_edl(recording_path: Path) -> Path:
    """User-facing EDL beside the recording (same folder as .srt)."""
    return recording_path.with_suffix(".edl")


def comskip_sidecar_txt(recording_path: Path) -> Path:
    return comskip_artifact_dir(recording_path) / f"{recording_path.stem}.txt"


def comskip_sidecar_chapters(recording_path: Path) -> Path:
    return comskip_artifact_dir(recording_path) / f"{recording_path.stem}.chapters.ffmeta"


def comskip_sidecar_manifest(recording_path: Path) -> Path:
    return comskip_artifact_dir(recording_path) / f"{recording_path.stem}.comskip.json"


def comskip_sidecar_failed(recording_path: Path) -> Path:
    return comskip_artifact_dir(recording_path) / f"{recording_path.stem}.comskip.failed.txt"


def comskip_run_ok(exit_code: int, *, edl_ok: bool, txt_ok: bool) -> bool:
    """Comskip exits 0 when no commercials are found and 1 when they are."""
    if exit_code == 0:
        return True
    if exit_code == 1:
        return edl_ok or txt_ok
    return False


def publish_edl_beside_recording(
    work_edl: Path | None,
    recording_path: Path,
) -> Path | None:
    """Copy a work-dir EDL next to the recording; return the published path."""
    if work_edl is None or not work_edl.is_file() or work_edl.stat().st_size <= 0:
        return None
    dest = comskip_sidecar_edl(recording_path)
    if work_edl.resolve() == dest.resolve():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(work_edl, dest)
    return dest


def build_comskip_argv(
    exe: Path,
    input_ts: Path,
    *,
    ini_path: Path,
    output_dir: Path,
) -> list[str]:
    return [
        str(exe),
        f"--ini={ini_path}",
        f"--output={output_dir}",
        "-t",
        str(input_ts),
    ]


def try_run_comskip(
    input_ts: Path,
    *,
    ini_path: Path | None = None,
    log_file: Path | None = None,
    output_dir: Path | None = None,
) -> ComskipRunResult:
    """Run Comskip; writes work artifacts (log/logo/edl/txt) under output_dir."""
    exe = comskip_exe()
    ini = ini_path or comskip_ini()
    if not exe.is_file():
        return ComskipRunResult(False, 127, None, None)
    if not ini.is_file():
        return ComskipRunResult(False, 127, None, None)

    out = output_dir or comskip_artifact_dir(input_ts)
    out.mkdir(parents=True, exist_ok=True)
    argv = build_comskip_argv(exe, input_ts, ini_path=ini, output_dir=out)
    code = run_tool(
        argv,
        log_file=log_file,
        cwd=out,
        console_guard=GUARD_COMSKIP,
    )
    edl = out / f"{input_ts.stem}.edl"
    txt = out / f"{input_ts.stem}.txt"
    edl_ok = edl.is_file() and edl.stat().st_size > 0
    txt_ok = txt.is_file() and txt.stat().st_size > 0
    ok = comskip_run_ok(code, edl_ok=edl_ok, txt_ok=txt_ok)
    return ComskipRunResult(
        ok=ok,
        exit_code=code,
        edl_path=edl if edl_ok else None,
        txt_path=txt if txt_ok else None,
    )
