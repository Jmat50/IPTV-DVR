"""Post-processing helpers run after recording finishes."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from paths import comskip_ini, ffmpeg_exe, resolve_commercial_cleaner_exe, resolve_comskip_exe


@dataclass
class PostprocessResult:
    success: bool
    exit_code: int
    output_path: Path
    message: str = ""


def _append_log_header(log_file: Path, title: str, argv: list[str]) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as log_fp:
        log_fp.write(f"\n---\n[{title}]\n$ {' '.join(argv)}\n")


def _run_logged(argv: list[str], *, log_file: Path, title: str) -> int:
    _append_log_header(log_file, title, argv)
    with open(log_file, "a", encoding="utf-8") as log_fp:
        p = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        assert p.stdout is not None
        for line in p.stdout:
            log_fp.write(line)
            log_fp.flush()
        return int(p.wait())


def _next_available(path: Path) -> Path:
    if not path.exists():
        return path
    idx = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{idx}{path.suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def generate_edl_with_comskip(input_path: Path, *, log_file: Path) -> Path:
    comskip = resolve_comskip_exe()
    if comskip is None:
        raise FileNotFoundError("Comskip not found (expected tools/comskip/comskip.exe or PATH)")

    ini = comskip_ini()
    argv = [str(comskip)]
    if ini.is_file():
        argv.append(f"--ini={ini}")
    argv.append(str(input_path))

    code = _run_logged(argv, log_file=log_file, title="postprocess: comskip")
    if code != 0:
        raise RuntimeError(f"Comskip failed with exit code {code}")

    edl = input_path.with_suffix(".edl")
    if not edl.is_file():
        raise FileNotFoundError(f"Comskip completed but no EDL file was found at {edl}")
    return edl


def clean_with_commercial_cleaner(input_path: Path, *, log_file: Path) -> Path:
    cleaner = resolve_commercial_cleaner_exe()
    if cleaner is None:
        raise FileNotFoundError(
            "CommercialCleaner not found (expected tools/commercialcleaner/CommercialCleaner.exe or PATH)",
        )

    ffmpeg_dir = ffmpeg_exe().parent
    default_clean = input_path.with_name(f"{input_path.stem}_clean.mkv")
    reserved_prior_clean: Path | None = None

    # CommercialCleaner always writes "<input>_clean.mkv". If that file already
    # exists, move it aside first so no prior cleaned result is overwritten.
    if default_clean.exists():
        reserved_prior_clean = _next_available(default_clean)
        default_clean.replace(reserved_prior_clean)

    # README contains inconsistent flag spellings; try both for compatibility.
    candidates = [
        [
            str(cleaner),
            f"-ffmpegpPath={ffmpeg_dir}",
            f"-inFile={input_path}",
        ],
        [
            str(cleaner),
            f"-mpegPath={ffmpeg_dir}",
            f"-inFile={input_path}",
        ],
    ]
    last_code = 0
    for idx, argv in enumerate(candidates, start=1):
        code = _run_logged(argv, log_file=log_file, title=f"postprocess: commercial cleaner attempt {idx}")
        last_code = code
        if code == 0:
            break
    else:
        raise RuntimeError(f"CommercialCleaner failed with exit code {last_code}")

    if not default_clean.is_file():
        # If cleaner failed to produce output, restore the previous clean file name.
        if reserved_prior_clean is not None and reserved_prior_clean.is_file():
            reserved_prior_clean.replace(default_clean)
        raise FileNotFoundError(
            f"CommercialCleaner completed but no cleaned file was found at {default_clean}",
        )

    # Keep cleaner output as canonical "_clean.mkv"; if we preserved an older
    # cleaned file, it remains as "_clean_#.mkv".
    return default_clean


def run_postprocessing(job, *, recorded_path: Path, log_file: Path) -> PostprocessResult:
    if not job.remove_commercials_after_complete:
        return PostprocessResult(True, 0, recorded_path)

    current = recorded_path
    try:
        if job.remove_commercials_after_complete:
            _ = generate_edl_with_comskip(current, log_file=log_file)
            current = clean_with_commercial_cleaner(current, log_file=log_file)
    except Exception as exc:
        return PostprocessResult(False, 3, current, str(exc))

    return PostprocessResult(True, 0, current)
