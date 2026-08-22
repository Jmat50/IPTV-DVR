"""Per-job Comskip.ini overrides (defaults match bundled comskip.ini)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


# detect_method bit masks
DM_BLACK_FRAME = 1
DM_LOGO = 2
DM_SCENE_CHANGE = 4
DM_FUZZY = 8
DM_CLOSED_CAPTIONS = 16
DM_ASPECT_RATIO = 32
DM_SILENCE = 64
DM_CUTSCENES = 128

# Bundled template default: black + logo + fuzzy + AR
DEFAULT_DETECT_METHOD = DM_BLACK_FRAME | DM_LOGO | DM_FUZZY | DM_ASPECT_RATIO  # 43


@dataclass
class ComskipSettings:
    detect_black_frame: bool = True
    detect_logo: bool = True
    detect_scene_change: bool = False
    detect_fuzzy: bool = True
    detect_closed_captions: bool = False
    detect_aspect_ratio: bool = True
    detect_silence: bool = False
    detect_cutscenes: bool = False
    subtitles: bool = False
    logo_at_bottom: bool = False
    connect_blocks_with_logo: bool = True
    punish_no_logo: bool = True
    aggressive_logo_rejection: bool = False
    cut_on_ar_change: int = 1  # 0, 1, or 2
    ticker_tape: int = 0
    shrink_logo: int = 5
    min_commercialbreak: int = 25
    max_commercialbreak: int = 600
    min_commercial_size: int = 4
    max_commercial_size: int = 125
    min_show_segment_length: int = 250

    def detect_method(self) -> int:
        v = 0
        if self.detect_black_frame:
            v |= DM_BLACK_FRAME
        if self.detect_logo:
            v |= DM_LOGO
        if self.detect_scene_change:
            v |= DM_SCENE_CHANGE
        if self.detect_fuzzy:
            v |= DM_FUZZY
        if self.detect_closed_captions:
            v |= DM_CLOSED_CAPTIONS
        if self.detect_aspect_ratio:
            v |= DM_ASPECT_RATIO
        if self.detect_silence:
            v |= DM_SILENCE
        if self.detect_cutscenes:
            v |= DM_CUTSCENES
        return v

    def ini_overrides(self) -> dict[str, str]:
        """Flat key=value strings for ini materialization (no spaces around =)."""
        return {
            "detect_method": str(self.detect_method()),
            "subtitles": "1" if self.subtitles else "0",
            "logo_at_bottom": "1" if self.logo_at_bottom else "0",
            "connect_blocks_with_logo": "1" if self.connect_blocks_with_logo else "0",
            "punish_no_logo": "1" if self.punish_no_logo else "0",
            "aggressive_logo_rejection": "1" if self.aggressive_logo_rejection else "0",
            "cut_on_ar_change": str(max(0, min(2, int(self.cut_on_ar_change)))),
            "ticker_tape": str(max(0, int(self.ticker_tape))),
            "shrink_logo": str(max(0, int(self.shrink_logo))),
            "min_commercialbreak": str(max(0, int(self.min_commercialbreak))),
            "max_commercialbreak": str(max(0, int(self.max_commercialbreak))),
            "min_commercial_size": str(max(0, int(self.min_commercial_size))),
            "max_commercial_size": str(max(0, int(self.max_commercial_size))),
            "min_show_segment_length": str(max(0, int(self.min_show_segment_length))),
        }


def detect_method_from_bits(
    *,
    black: bool,
    logo: bool,
    scene: bool,
    fuzzy: bool,
    cc: bool,
    ar: bool,
    silence: bool,
    cutscenes: bool,
) -> int:
    s = ComskipSettings(
        detect_black_frame=black,
        detect_logo=logo,
        detect_scene_change=scene,
        detect_fuzzy=fuzzy,
        detect_closed_captions=cc,
        detect_aspect_ratio=ar,
        detect_silence=silence,
        detect_cutscenes=cutscenes,
    )
    return s.detect_method()


def bits_from_detect_method(method: int) -> dict[str, bool]:
    m = int(method)
    return {
        "detect_black_frame": bool(m & DM_BLACK_FRAME),
        "detect_logo": bool(m & DM_LOGO),
        "detect_scene_change": bool(m & DM_SCENE_CHANGE),
        "detect_fuzzy": bool(m & DM_FUZZY),
        "detect_closed_captions": bool(m & DM_CLOSED_CAPTIONS),
        "detect_aspect_ratio": bool(m & DM_ASPECT_RATIO),
        "detect_silence": bool(m & DM_SILENCE),
        "detect_cutscenes": bool(m & DM_CUTSCENES),
    }


def _as_bool(v: Any, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


def _as_int(v: Any, default: int, *, lo: int | None = None, hi: int | None = None) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        n = default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def comskip_settings_from_dict(d: Any) -> ComskipSettings:
    """Load settings; missing keys use bundled defaults. Accepts detect_method int as shortcut."""
    base = ComskipSettings()
    if not isinstance(d, dict):
        return base
    data = dict(d)
    if "detect_method" in data and not any(
        k in data
        for k in (
            "detect_black_frame",
            "detect_logo",
            "detect_scene_change",
            "detect_fuzzy",
            "detect_closed_captions",
            "detect_aspect_ratio",
            "detect_silence",
            "detect_cutscenes",
        )
    ):
        bits = bits_from_detect_method(_as_int(data.get("detect_method"), DEFAULT_DETECT_METHOD))
        data.update(bits)
    bool_fields = {
        "detect_black_frame",
        "detect_logo",
        "detect_scene_change",
        "detect_fuzzy",
        "detect_closed_captions",
        "detect_aspect_ratio",
        "detect_silence",
        "detect_cutscenes",
        "subtitles",
        "logo_at_bottom",
        "connect_blocks_with_logo",
        "punish_no_logo",
        "aggressive_logo_rejection",
    }
    kwargs: dict[str, Any] = {}
    for f in fields(ComskipSettings):
        if f.name not in data:
            continue
        if f.name in bool_fields:
            kwargs[f.name] = _as_bool(data[f.name], getattr(base, f.name))
        elif f.name == "cut_on_ar_change":
            kwargs[f.name] = _as_int(data[f.name], base.cut_on_ar_change, lo=0, hi=2)
        else:
            kwargs[f.name] = _as_int(data[f.name], getattr(base, f.name), lo=0)
    return ComskipSettings(**{**asdict(base), **kwargs})


def comskip_settings_to_dict(settings: ComskipSettings) -> dict[str, Any]:
    d = asdict(settings)
    d["detect_method"] = settings.detect_method()
    return d
