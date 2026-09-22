"""Deterministic parsing and normalization for local VTT/SRT caption files."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

STAMP = re.compile(r"^(?:(\d+):)?(\d{2}):([0-5]\d)[.,](\d{3})$")

class CaptionError(ValueError):
    """Raised when a caption file cannot be safely normalized."""

@dataclass(frozen=True)
class Cue:
    id: str
    start: float
    end: float
    text: str

def _seconds(value: str) -> float:
    match = STAMP.match(value.strip())
    if not match:
        raise CaptionError(f"invalid timestamp: {value!r}")
    hours = int(match.group(1) or 0)
    return hours * 3600 + int(match.group(2)) * 60 + int(match.group(3)) + int(match.group(4)) / 1000

def _parse(body: str, *, srt: bool) -> list[Cue]:
    body = body.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not srt and not body.startswith("WEBVTT"):
        raise CaptionError("VTT must start with WEBVTT")
    cues: list[Cue] = []
    for number, block in enumerate(re.split(r"\n\s*\n", body), 1):
        lines = block.splitlines()
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        left, right = [part.strip() for part in lines[timing_index].split("-->", 1)]
        start = _seconds(left.split()[0]); end = _seconds(right.split()[0])
        if end <= start:
            raise CaptionError(f"cue {number} has non-positive duration")
        text = html.unescape(re.sub(r"<[^>]+>", "", "\n".join(lines[timing_index + 1:])).strip())
        if text:
            cues.append(Cue(str(number), start, end, text))
    if not cues:
        raise CaptionError("no caption cues found")
    return cues

def parse_vtt(body: str) -> list[Cue]: return _parse(body, srt=False)
def parse_srt(body: str) -> list[Cue]: return _parse(body, srt=True)

def load_captions(path: Path) -> list[Cue]:
    body = path.read_text(encoding="utf-8-sig")
    suffix = path.suffix.lower()
    if suffix == ".vtt": return parse_vtt(body)
    if suffix == ".srt": return parse_srt(body)
    if suffix == ".txt":
        raise CaptionError("TXT has no timestamps; timed caption parsing requires VTT or SRT")
    raise CaptionError(f"unsupported caption format: {path.suffix}")

def _stamp(value: float, comma: bool = False) -> str:
    ms = max(0, round(value * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02}{',' if comma else '.'}{ms:03}"

def write_vtt(cues: list[Cue], path: Path) -> None:
    path.write_text("WEBVTT\n\n" + "\n\n".join(f"{_stamp(c.start)} --> {_stamp(c.end)}\n{c.text}" for c in cues) + "\n", encoding="utf-8")

def write_srt(cues: list[Cue], path: Path) -> None:
    path.write_text("\n\n".join(f"{i}\n{_stamp(c.start, True)} --> {_stamp(c.end, True)}\n{c.text}" for i, c in enumerate(cues, 1)) + "\n", encoding="utf-8")
