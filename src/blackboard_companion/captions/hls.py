"""HLS subtitle timeline handling, migrated from the NTU prototype.

Times are seconds. MPEGTS uses a 90 kHz clock with 33-bit rollover.
The first mapped segment is an assumed origin unless explicitly supplied.
"""
from __future__ import annotations

import html
import json
import math
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from ..storage import atomic_bytes

STAMP = r'(?:\d+:)?\d{2}:\d{2}[.,]\d{3}'
TIMING = re.compile(rf'^({STAMP})\s+-->\s+({STAMP})(.*)$')
WRAP = 2 ** 33 / 90000


class SubtitleError(Exception):
    """Safe, user-facing exception with no network secrets."""


def log(message):
    print(message, flush=True)


def seconds(value):
    parts = value.replace(',', '.').split(':')
    return sum(float(part) * 60 ** index for index, part in enumerate(reversed(parts)))


def timestamp(value, srt=False):
    ms = max(0, round(value * 1000))
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f'{hours:02}:{minutes:02}:{sec:02}{"," if srt else "."}{ms:03}'


@dataclass
class Cue:
    start: float
    end: float
    text: str
    settings: str = ''


@dataclass
class Segment:
    url: str
    start: float
    duration: float
    discontinuity: bool = False


def attributes(line):
    return {key: quoted if quoted else plain for key, quoted, plain in
            re.findall(r'([\w-]+)=(?:"([^"]*)"|([^,]*))', line)}


def parse_playlist(body, base):
    lines = [line.strip() for line in body.lstrip('\ufeff').splitlines() if line.strip()]
    if not lines or lines[0] != '#EXTM3U':
        raise SubtitleError('响应不是有效的 M3U8 playlist。')
    children, segments = [], []
    duration, position, discontinuity = None, 0.0, False
    for line in lines:
        if line.startswith('#EXT-X-KEY:') and attributes(line).get('METHOD') != 'NONE':
            raise SubtitleError('字幕 playlist 使用加密，当前工具不支持。')
        if line.startswith(('#EXT-X-BYTERANGE:', '#EXT-X-MAP:')):
            raise SubtitleError('该字幕使用 byte-range/init segment，不能按普通 VTT 分片处理。')
        if line.startswith('#EXT-X-MEDIA:'):
            attr = attributes(line)
            if attr.get('TYPE') == 'SUBTITLES' and attr.get('URI'):
                children.append((attr.get('LANGUAGE', '') + ' ' + attr.get('NAME', ''),
                                 urljoin(base, attr['URI'])))
        elif line.startswith('#EXTINF:'):
            duration = float(line.split(':', 1)[1].split(',')[0])
            if not math.isfinite(duration) or duration < 0:
                raise SubtitleError('playlist 中的分片时长无效。')
        elif line == '#EXT-X-DISCONTINUITY':
            discontinuity = True
        elif not line.startswith('#') and duration is not None:
            segments.append(Segment(urljoin(base, line), position, duration, discontinuity))
            position += duration
            duration, discontinuity = None, False
    children.sort(key=lambda item: not bool(re.search(r'\ben(?:g)?\b|english', item[0], re.I)))
    return segments, children, '#EXT-X-ENDLIST' in lines


def parse_vtt(body):
    body = body.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    if not body.startswith('WEBVTT'):
        raise SubtitleError('分片响应不是 WEBVTT（可能登录已过期或返回了错误页）。')
    mapping = None
    match = re.search(r'X-TIMESTAMP-MAP\s*=([^\n]+)', body)
    if match:
        local = re.search(r'LOCAL:(' + STAMP + r')', match[1])
        mpeg = re.search(r'MPEGTS:(\d+)', match[1])
        if not local or not mpeg:
            raise SubtitleError('无法解析 X-TIMESTAMP-MAP。')
        mapping = (seconds(local[1]), int(mpeg[1]) / 90000)
    cues = []
    for block in re.split(r'\n\s*\n', body):
        lines = block.splitlines()
        if not lines or lines[0].startswith(('NOTE', 'STYLE', 'REGION')):
            continue
        for index, line in enumerate(lines):
            match = TIMING.match(line.strip())
            if match:
                start, end = seconds(match[1]), seconds(match[2])
                if end <= start:
                    raise SubtitleError('发现结束时间不晚于开始时间的 cue。')
                cues.append(Cue(start, end, '\n'.join(lines[index + 1:]), match[3].strip()))
                break
    return cues, mapping


def merge_segments(segments, bodies, mode='auto', mpegts_origin=None):
    result, warnings, seen = [], [], set()
    origin = mpegts_origin
    previous_mpeg = None
    previous_start = -1.0
    duplicates = 0
    for index, (segment, body) in enumerate(zip(segments, bodies, strict=True)):
        cues, mapping = parse_vtt(body)
        shift = 0.0
        if mapping:
            local, mpeg = mapping
            if previous_mpeg is not None:
                mpeg += round((previous_mpeg - mpeg) / WRAP) * WRAP
            previous_mpeg = mpeg
            if origin is None:
                # First segment anchors the media timeline; MPEGTS is not wall time.
                origin = mpeg - local - segment.start
                warnings.append('MPEGTS 原点由首个带映射的分片推导；可用 --mpegts-origin 指定已知媒体 PTS 原点。')
            if segment.discontinuity:
                origin = mpeg - local - segment.start
                warnings.append(f'分片 {index + 1} 存在 DISCONTINUITY，按 playlist 累计时长重新锚定。')
            shift = mpeg - local - origin
        elif mode == 'local':
            shift = segment.start
        elif mode == 'auto' and cues and segment.start > 0:
            # Overlap across HLS boundaries is legal. Decide from actual intervals.
            absolute = any(c.end > segment.start - .05 and
                           c.start < segment.start + segment.duration + .05 for c in cues)
            local = all(c.start < segment.duration + .05 and c.end > 0 for c in cues)
            if local and not absolute:
                shift = segment.start
                warnings.append('无 X-TIMESTAMP-MAP 的分片按局部时间自动偏移；可用 --timestamps 覆盖判断。')
            elif not absolute:
                raise SubtitleError(f'分片 {index + 1} 的无映射时间轴不明确，请指定 --timestamps local 或 absolute。')
        for cue in cues:
            start, end = cue.start + shift, cue.end + shift
            if start < -.05:
                raise SubtitleError('字幕映射产生负时间，请检查 --mpegts-origin。')
            text = re.sub(r'<(' + STAMP + r')>',
                          lambda m: '<' + timestamp(seconds(m[1]) + shift) + '>', cue.text)
            key = (round(start * 1000), round(end * 1000), text, cue.settings)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            if start < previous_start - .05:
                warnings.append(f'分片 {index + 1} 存在跨分片重叠/倒序 cue，输出按开始时间排序。')
            previous_start = start
            result.append(Cue(max(0, start), end, text, cue.settings))
        if cues:
            lo, hi = min(c.start + shift for c in cues), max(c.end + shift for c in cues)
            if hi < segment.start - 1 or lo > segment.start + segment.duration + 1:
                raise SubtitleError(f'分片 {index + 1} 字幕范围与 playlist 时段不符，拒绝输出错误时间轴。')
    result.sort(key=lambda c: (c.start, c.end))
    if not result:
        raise SubtitleError('没有提取到字幕 cue。')
    gaps, last_end = [], result[0].end
    for cue in result[1:]:
        if cue.start - last_end > 30:
            gaps.append({'start': round(last_end, 3), 'end': round(cue.start, 3),
                         'seconds': round(cue.start - last_end, 3)})
        last_end = max(last_end, cue.end)
    duration = max(s.start + s.duration for s in segments)
    report = {'segments': len(segments), 'download_failures': 0, 'cues': len(result),
              'duplicates_removed': duplicates, 'timestamps_monotonic': True,
              'first_seconds': result[0].start, 'last_seconds': max(c.end for c in result),
              'playlist_duration_seconds': duration,
              'leading_silence_seconds': round(result[0].start, 3),
              'trailing_silence_seconds': round(max(0, duration - max(c.end for c in result)), 3),
              'gaps_over_30_seconds': gaps, 'warnings': list(dict.fromkeys(warnings))}
    return result, report


def plain(text):
    return html.unescape(re.sub(r'<[^>]*>', '', text))


def export(cues, output, name, report):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:140] or 'NTU_replay'
    if re.fullmatch(r'CON|PRN|AUX|NUL|COM\d|LPT\d', name, re.I):
        name = '_' + name
    output.mkdir(parents=True, exist_ok=True)
    # Preserve previous extractions rather than silently overwriting them.
    if any((output / (name + ext)).exists() for ext in ('.vtt', '.srt', '.txt')):
        name += '_' + time.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:4]
    vtt, srt = ['WEBVTT\n'], []
    for index, cue in enumerate(cues, 1):
        settings = ' ' + cue.settings if cue.settings else ''
        vtt.append(f'{timestamp(cue.start)} --> {timestamp(cue.end)}{settings}\n{cue.text}\n')
        srt.append(f'{index}\n{timestamp(cue.start, True)} --> {timestamp(cue.end, True)}\n{plain(cue.text)}\n')
    for suffix, text in (('.vtt', '\n'.join(vtt)), ('.srt', '\n'.join(srt)),
                         ('.txt', '\n'.join(plain(c.text) for c in cues) + '\n'),
                         ('.validation.json', json.dumps(report, ensure_ascii=False, indent=2))):
        atomic_bytes(output / (name + suffix), text.encode('utf-8'))
    return name

