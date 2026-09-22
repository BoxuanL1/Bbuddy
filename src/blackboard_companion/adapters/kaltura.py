"""Browser-context caption discovery and downloads for Kaltura-style streams."""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urljoin, urlsplit

from ..captions.hls import SubtitleError, parse_playlist, parse_vtt, log

PATTERN = re.compile(r"servewebvtt|captionassetid|caption_captionasset|\.m3u8|\.vtt", re.I)

class Capture:
    def __init__(self, context):
        self.context = context
        self.requests = {}
        self.candidates = {}
        self.source_pages = {}
        self.tasks = set()
        self.total_requests = self.total_responses = 0
        # Context events include frames, popups and every page, before navigation.
        context.on('request', self.on_request)
        context.on('response', self.on_response)

    def on_request(self, request):
        self.total_requests += 1
        if PATTERN.search(request.url):
            self.requests[request.url] = request

    def on_response(self, response):
        self.total_responses += 1
        content_type = response.headers.get('content-type', '').lower()
        if PATTERN.search(response.url) or any(x in content_type for x in ('mpegurl', 'text/vtt')):
            task = asyncio.create_task(self.inspect(response))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def inspect(self, response):
        try:
            if response.status != 200:
                return
            body = await response.text()
            if not body.lstrip('\ufeff\r\n ').startswith(('#EXTM3U', 'WEBVTT')):
                return
            headers = await response.request.all_headers()
            self.requests[response.url] = response.request
            self.candidates[response.url] = (body, headers)
            try:
                self.source_pages[response.url] = response.request.frame.page
            except Exception:
                pass
        except Exception:
            pass  # Page may close; never leak signed URLs in exception text.

    async def headers_for(self, url, fallback_url, fallback):
        if url in self.requests:
            source = await self.requests[url].all_headers()
        else:
            source = dict(fallback)
            # Do not copy credentials to a different host. Context supplies cookies.
            if urlsplit(url)[:2] != urlsplit(fallback_url)[:2]:
                source = {k: v for k, v in source.items()
                          if k.lower() in ('accept', 'accept-language', 'user-agent', 'referer', 'origin')}
        drop = {'cookie', 'host', 'content-length', 'connection', 'accept-encoding',
                'range', 'if-none-match', 'if-modified-since'}
        return {k: v for k, v in source.items() if k.lower() not in drop and not k.startswith(':')}


async def download(context, url, headers, attempts=3):
    for attempt in range(attempts):
        response = None
        try:
            # No automatic cross-origin redirect forwarding of captured credentials.
            response = await context.request.get(url, headers=headers, timeout=30000, max_redirects=0)
            if 200 <= response.status < 300:
                return await response.text()
            if response.status in (401, 403):
                raise SubtitleError('字幕下载被拒绝（401/403）；请运行 --login 更新登录状态。')
            if 300 <= response.status < 400:
                target = urljoin(url, response.headers.get('location', ''))
                if target == url or not target.startswith(('https://', 'http://')):
                    raise SubtitleError('字幕下载发生无效重定向。')
                if urlsplit(url).scheme == 'https' and urlsplit(target).scheme != 'https':
                    raise SubtitleError('拒绝字幕下载从 HTTPS 降级到 HTTP。')
                if urlsplit(target)[:2] != urlsplit(url)[:2]:
                    headers = {k: v for k, v in headers.items() if k.lower() in
                               ('accept', 'accept-language', 'user-agent', 'referer', 'origin')}
                url = target
            elif attempt == attempts - 1:
                raise SubtitleError(f'字幕下载失败，HTTP {response.status}。')
        except SubtitleError:
            raise
        except Exception:
            if attempt == attempts - 1:
                raise SubtitleError('字幕下载网络错误，重试后仍失败。') from None
        finally:
            if response:
                await response.dispose()
        await asyncio.sleep(.5 * 2 ** attempt)
    raise SubtitleError('字幕下载重定向次数过多。')


async def activate(context, actions):
    for page in context.pages:
        for frame in page.frames:
            for kind, regex in [('play', r'^(play|play video|播放)(\b|$)'),
                                ('cc', r'caption|subtitle|^cc$|字幕'),
                                ('english', r'english|英语|英文')]:
                key = (id(frame), kind)
                if key in actions:
                    continue
                try:
                    locator = frame.get_by_role('button', name=re.compile(regex, re.I))
                    if kind == 'english' and not await locator.count():
                        locator = frame.get_by_text(re.compile(r'^English(?:\s.*)?$', re.I))
                    for index in range(min(await locator.count(), 8)):
                        item = locator.nth(index)
                        if await item.is_visible():
                            await item.click(timeout=1000)
                            actions.add(key)
                            break
                except Exception:
                    pass


async def resolve_playlist(context, capture, url, body, headers, cache, depth=0):
    if depth > 4:
        raise SubtitleError('playlist 嵌套过深。')
    segments, children, ended = parse_playlist(body, url)
    if children:
        child = children[0][1]
        h = await capture.headers_for(child, url, headers)
        body = await download(context, child, h)
        return await resolve_playlist(context, capture, child, body, h, cache, depth + 1)
    if not segments:
        raise SubtitleError('playlist 未包含字幕分片。')
    # Reject video/audio playlists before downloading their segments.
    is_caption = bool(re.search(r'servewebvtt|caption|\.vtt(?:$|[?/#])', url, re.I))
    if not is_caption and not all(re.search(r'\.vtt(?:$|[?#])|servewebvtt|caption', s.url, re.I) for s in segments):
        raise SubtitleError('该 playlist 不是可识别的字幕轨道。')
    if not ended:
        raise SubtitleError('字幕 playlist 没有 ENDLIST，无法确认回放字幕完整；拒绝输出部分结果。')
    cache.mkdir(parents=True, exist_ok=True)
    (cache / 'a.m3u8').write_text(body, encoding='utf-8')
    bodies, failures = [], []
    log(f'已发现字幕 playlist，共 {len(segments)} 个分片。')
    for index, segment in enumerate(segments, 1):
        try:
            h = await capture.headers_for(segment.url, url, headers)
            text = await download(context, segment.url, h)
            parse_vtt(text)
            (cache / f'{index:05}.vtt').write_text(text, encoding='utf-8')
            bodies.append(text)
            log(f'下载字幕分片 {index}/{len(segments)} 完成。')
        except SubtitleError as exc:
            failures.append(index)
            log(f'分片 {index} 失败：{exc}')
    if failures:
        (cache / 'failure.json').write_text(json.dumps({'segments': len(segments), 'failed_segments': failures}), encoding='utf-8')
        raise SubtitleError(f'{len(failures)} 个分片下载失败；没有生成不完整字幕。')
    return segments, bodies

