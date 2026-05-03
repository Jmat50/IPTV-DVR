"""Minimal M3U loader (file or http(s)) matching the Go iptvrecord parser."""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Channel:
    name: str
    url: str
    user_agent: str = ""
    referer: str = ""


def load_m3u(path_or_url: str, timeout: int = 60) -> list[Channel]:
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        req = urllib.request.Request(path_or_url, headers={"User-Agent": "iptv-recorder-gui/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8", errors="replace")
    else:
        text = Path(path_or_url).read_text(encoding="utf-8", errors="replace")
    ch = parse_m3u(text)
    if ch:
        return ch
    raise ValueError(_no_channels_message(text, path_or_url))


def parse_m3u(text: str) -> list[Channel]:
    out: list[Channel] = []
    cur = Channel(name="", url="")
    for raw in text.splitlines():
        line = raw.strip().strip("\r")
        if not line:
            continue
        if line.startswith("#EXTINF"):
            cur = Channel(name=_extinf_title(line), url="")
        elif line.startswith("#EXTVLCOPT:"):
            opt = line[len("#EXTVLCOPT:") :]
            if opt.startswith("http-user-agent="):
                cur.user_agent = opt[len("http-user-agent=") :]
            elif opt.startswith("http-referrer="):
                cur.referer = opt[len("http-referrer=") :]
        elif line.startswith("#"):
            continue
        elif _is_stream_url(line):
            cur.url = line
            if cur.name:
                out.append(cur)
            cur = Channel(name="", url="")
    return out


def _extinf_title(line: str) -> str:
    i = line.rfind(",")
    if i >= 0 and i + 1 < len(line):
        return line[i + 1 :].strip()
    return line.strip()


def _is_stream_url(s: str) -> bool:
    return bool(
        re.match(r"^(https?|rtmp|rtsp)://", s, re.I),
    )


def _no_channels_message(text: str, source: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    extinf = sum(1 for ln in lines if ln.upper().startswith("#EXTINF"))
    stream_urls = sum(1 for ln in lines if _is_stream_url(ln))
    has_extm3u = any(ln.upper().startswith("#EXTM3U") for ln in lines[:20])
    looks_html = "<html" in text.lower() or "<!doctype html" in text.lower()
    hints: list[str] = []
    if looks_html:
        hints.append("Source appears to be HTML/login page, not raw M3U text.")
    if not has_extm3u:
        hints.append("Playlist header #EXTM3U was not found.")
    if extinf == 0 and stream_urls > 0:
        hints.append("Found stream URLs but no #EXTINF lines (provider format unsupported).")
    if extinf > 0 and stream_urls == 0:
        hints.append("Found #EXTINF lines but no stream URL lines after them.")
    if extinf == 0 and stream_urls == 0:
        hints.append("No recognizable channel entries were detected.")
    return (
        f'No channels found in "{source}".\n'
        f"Detected: EXTINF={extinf}, stream_urls={stream_urls}, header_EXTM3U={'yes' if has_extm3u else 'no'}.\n"
        + " ".join(hints)
        + "\nTip: open the source in a text editor and verify it contains lines like "
        '"#EXTINF:...,Channel Name" followed by "http(s)://...".'
    )


def find_channel(channels: list[Channel], name: str) -> Channel:
    want = name.strip().lower()
    if not want:
        raise ValueError("empty channel name")
    exact: Channel | None = None
    partial: list[Channel] = []
    for c in channels:
        n = c.name.strip().lower()
        if n == want:
            exact = c
            break
        if want in n:
            partial.append(c)
    if exact is not None:
        return exact
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise LookupError(f'no channel matching "{name}"')
    preview = "; ".join(c.name for c in partial[:8])
    raise LookupError(f'ambiguous channel "{name}": {preview}')
