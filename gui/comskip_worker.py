"""Run Comskip commercial detection on finished MPEG-TS recordings."""

from __future__ import annotations

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
    return comskip_artifact_dir(recording_path) / f"{recording_path.stem}.edl"


def comskip_sidecar_txt(recording_path: Path) -> Path:
    return comskip_artifact_dir(recording_path) / f"{recording_path.stem}.txt"


def comskip_sidecar_chapters(recording_path: Path) -> Path:
    return comskip_artifact_dir(recording_path) / f"{recording_path.stem}.chapters.ffmeta"


def comskip_sidecar_manifest(recording_path: Path) -> Path:
    return comskip_artifact_dir(recording_path) / f"{recording_path.stem}.comskip.json"


def comskip_sidecar_failed(recording_path: Path) -> Path:
    return comskip_artifact_dir(recording_path) / f"{recording_path.stem}.comskip.failed.txt"


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
    """Run Comskip on a finished .ts file; sidecars go under output_dir (logs)."""
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
    ok = code == 0 and (edl_ok or txt_ok)
    return ComskipRunResult(
        ok=ok,
        exit_code=code,
        edl_path=edl if edl_ok else None,
        txt_path=txt if txt_ok else None,
    )
