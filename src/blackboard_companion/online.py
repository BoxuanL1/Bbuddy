"""Agent-selected online acquisition. Discovery is a snapshot, not a full catalog."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from .adapters.kaltura import Capture, activate, resolve_playlist
from .adapters.blackboard import defer_notifications
from .captions.hls import SubtitleError, export, merge_segments
from .storage import atomic_bytes, profile_dir, write_json

NTU_SITE = 'https://ntulearn.ntu.edu.sg'


def require_https(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Expected an HTTPS URL without embedded credentials.')
    return url


@asynccontextmanager
async def session(args):
    from playwright.async_api import async_playwright

    require_https(args.site)
    root = profile_dir(args.site, args.account, args.data_dir)
    state = root / 'auth' / 'state.json'
    async with async_playwright() as playwright:
        channel = None if args.browser == 'chromium' else args.browser
        browser = await playwright.chromium.launch(channel=channel, headless=False)
        try:
            options = {'storage_state': str(state)} if state.exists() and args.command != 'login' else {}
            context = await browser.new_context(**options)
            yield context, root
        finally:
            await browser.close()


async def save_state(context, root: Path) -> None:
    write_json(root / 'auth' / 'state.json', await context.storage_state(indexed_db=True))


async def login(context, root: Path, site: str, timeout: int, page=None) -> dict:
    """Detect the known NTU authenticated UI after manual SSO/MFA."""
    if site.rstrip('/') != NTU_SITE:
        raise ValueError('Login detection currently supports NTU only.')
    page = page or await context.new_page()
    if page.url != site and page.url.rstrip('/') != site.rstrip('/'):
        await page.goto(site, wait_until='domcontentloaded')
    print('请在可见浏览器完成 SSO/MFA；进入课程界面后保存登录状态。', flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for current in context.pages:
            if urlsplit(current.url).hostname != urlsplit(site).hostname or '/ultra/' not in current.url:
                continue
            navigation = current.locator('bb-base-navigation, bb-course-list, bb-course-content')
            courses = current.get_by_role('link', name=re.compile(r'^Courses$|^课程$'))
            if await navigation.count() or await courses.count():
                await defer_notifications(context, root / 'notifications')
                await save_state(context, root)
                return {'state': 'authenticated'}
        if not context.pages:
            raise SubtitleError('登录窗口已关闭。')
        await asyncio.sleep(1)
    raise SubtitleError('登录等待超时；未保存未确认的状态。')


async def discover(context, url: str, output: Path, settle_seconds: float) -> dict:
    """Store rendered links privately; dynamic folders still require agent navigation."""
    page = await context.new_page()
    await page.goto(require_https(url), wait_until='domcontentloaded')
    await asyncio.sleep(settle_seconds)
    await defer_notifications(context, output.parent / 'notifications')
    if urlsplit(page.url).hostname != urlsplit(url).hostname or re.search(r'/login|/auth', page.url, re.I):
        raise SubtitleError('页面进入登录流程，请先运行 login。')
    resources, seen = [], set()
    for frame in page.frames:
        try:
            links = await frame.locator('a[href]').evaluate_all('''nodes => nodes
                .filter(a => a.getClientRects().length)
                .map(a => ({label: a.innerText.trim(), url: a.href}))''')
        except Exception:
            continue
        for link in links:
            href = link['url']
            if not href.startswith('https://') or href in seen:
                continue
            seen.add(href)
            resources.append({'id': hashlib.sha256(href.encode()).hexdigest()[:16], **link})
    write_json(output, {'page_url': url, 'resources': resources, 'complete': False})
    return {'state': 'discovered' if resources else 'needs_selection', 'resources': len(resources),
            'inventory': str(output), 'complete': False}


def check_document(data: bytes, kind: str, content_type: str) -> None:
    """Reject login HTML and file bodies that do not match the selected format."""
    if 'html' in content_type.lower():
        raise SubtitleError('下载返回 HTML，可能需要重新登录或使用真实文件链接。')
    if kind == 'pdf' and data.startswith(b'%PDF-'):
        return
    if kind == 'pptx':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if 'ppt/presentation.xml' in archive.namelist():
                    return
        except zipfile.BadZipFile:
            pass
    raise SubtitleError('文件内容与声明的 PDF/PPTX 类型不符。')


async def fetch_document(context, url: str, kind: str) -> bytes:
    """Reuse scoped context cookies; require re-resolution of redirected links."""
    require_https(url)
    for attempt in range(3):
        response = None
        try:
            response = await context.request.get(url, max_redirects=0, timeout=30000)
            status = response.status
            if status == 200:
                data = await response.body()
                check_document(data, kind, response.headers.get('content-type', ''))
                return data
            if status in (401, 403):
                raise SubtitleError('文件访问被拒绝；请更新登录状态或重新发现过期链接。')
            if 300 <= status < 400:
                raise SubtitleError('文件链接重定向；请在浏览器确认最终链接后更新清单。')
            if status != 429 and status < 500:
                raise SubtitleError(f'文件下载失败，HTTP {status}。')
        except SubtitleError:
            raise
        except Exception:
            if attempt == 2:
                raise SubtitleError('文件下载网络错误。') from None
        finally:
            if response is not None:
                await response.dispose()
        if attempt < 2:
            await asyncio.sleep(0.5 * 2 ** attempt)
    raise SubtitleError('文件下载重试后仍失败。')


def read_plan(path: Path) -> list[dict]:
    """Validate a complete selection before opening the browser."""
    items = json.loads(path.read_text(encoding='utf-8-sig')).get('resources')
    if not isinstance(items, list) or not items:
        raise ValueError('Selection must contain a non-empty resources list.')
    seen = set()
    for item in items:
        identifier = item.get('id', '')
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', identifier):
            raise ValueError('Resource id must contain only letters, digits, underscores or hyphens.')
        if identifier.lower() in seen or re.fullmatch(r'CON|PRN|AUX|NUL|COM\d|LPT\d', identifier, re.I):
            raise ValueError('Duplicate or reserved resource id.')
        seen.add(identifier.lower())
        if item.get('kind') not in ('pdf', 'pptx'):
            raise ValueError('collect supports PDF/PPTX; use captions for replays.')
        require_https(item['url'])
    return items


async def collect(context, items: list[dict], output: Path) -> dict:
    """Checkpoint each resource; skip only an identical, hash-verified local copy."""
    manifest_path = output / 'acquisition.json'
    previous = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    old = {entry['id']: entry for entry in previous.get('resources', [])}
    entries = []
    report = {'stage': 'acquiring', 'resources': entries}
    for item in items:
        filename = f"{item['id']}.{item['kind']}"
        path = output / 'raw' / filename
        selection_hash = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        cached = old.get(item['id'], {})
        if (cached.get('selection_hash') == selection_hash and cached.get('status') == 'acquired'
                and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == cached.get('sha256')):
            entries.append(cached)
        else:
            entry = {'id': item['id'], 'kind': item['kind'], 'role': item.get('role'),
                     'path': f'raw/{filename}', 'selection_hash': selection_hash}
            try:
                data = await fetch_document(context, item['url'], item['kind'])
                atomic_bytes(path, data)
                entry.update(status='acquired', sha256=hashlib.sha256(data).hexdigest())
            except SubtitleError as exc:
                entry.update(status='failed', error=str(exc))
            entries.append(entry)
        write_json(manifest_path, report)
    report['stage'] = 'failed' if any(e['status'] == 'failed' for e in entries) else 'acquired'
    write_json(manifest_path, report)
    return report


def caption_candidates(capture, page, asset_id: str | None) -> list[tuple]:
    """Only accept playlists tied to the selected page and a recognizable asset."""
    matches = []
    for url, (body, headers) in list(capture.candidates.items()):
        if capture.source_pages.get(url) != page or not body.lstrip('\ufeff').startswith('#EXTM3U'):
            continue
        asset = re.search(r'captionAssetId[=/]([^/?&#]+)', url, re.I)
        if asset and (not asset_id or asset[1] == asset_id):
            matches.append((url, body, headers))
    return matches


async def captions(context, root: Path, args, page=None, capture=None) -> dict:
    """Bind captured requests to the chosen page; stop when track selection is ambiguous."""
    owns_capture = capture is None
    capture = capture or Capture(context)
    try:
        page = page or await context.new_page()
        require_https(args.url)
        if page.url != args.url:
            await page.goto(args.url, wait_until='domcontentloaded')
        selected_page_url = page.url
        print('正在捕获字幕；必要时在此回放中点击 CC → English。', flush=True)
        deadline, actions = time.monotonic() + args.timeout, set()
        previous_candidates, stable_since = (), time.monotonic()
        while time.monotonic() < deadline:
            if page.is_closed() or page.url != selected_page_url:
                raise SubtitleError('目标回放页面已关闭或导航改变；请重新选择回放。')
            await defer_notifications(context, args.output / 'notifications')
            await activate(context, actions)
            matches = caption_candidates(capture, page, args.caption_asset)
            current_candidates = tuple(sorted(match[0] for match in matches))
            if current_candidates != previous_candidates:
                previous_candidates, stable_since = current_candidates, time.monotonic()
            if len(matches) > 1:
                assets = sorted({re.search(r'captionAssetId[=/]([^/?&#]+)', m[0], re.I)[1] for m in matches})
                write_json(root / 'caption-candidates.json', {'asset_ids': assets})
                raise SubtitleError('发现多个字幕 playlist；候选资产 ID 已存入私有 profile 的 caption-candidates.json。')
            if matches and time.monotonic() - stable_since >= 2:
                url, body, headers = matches[0]
                cache = root / 'cache' / hashlib.sha256(url.encode()).hexdigest()[:16]
                segments, bodies = await resolve_playlist(context, capture, url, body, headers, cache)
                cues, report = merge_segments(segments, bodies, args.timestamps, args.mpegts_origin)
                report.update(caption_asset_id=re.search(r'captionAssetId[=/]([^/?&#]+)', url, re.I)[1],
                              replay_id=args.name, identity_basis='selected browser page and captured asset',
                              language_verified=False)
                name = export(cues, args.output, args.name, report)
                await save_state(context, root)
                return {'state': 'acquired', 'name': name, 'cues': len(cues), 'segments': len(segments)}
            await asyncio.sleep(1)
        raise SubtitleError('字幕捕获超时；请确认资产 ID、登录状态与 English CC。')
    finally:
        if owns_capture:
            context.remove_listener('request', capture.on_request)
            context.remove_listener('response', capture.on_response)
            tasks = list(capture.tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def run_online(args) -> dict:
    items = read_plan(args.selection) if args.command == 'collect' else None
    async with session(args) as (context, root):
        if args.command == 'login':
            return await login(context, root, args.site, args.timeout)
        if not (root / 'auth' / 'state.json').exists():
            raise SubtitleError('尚无该账户的登录状态，请先运行 login。')
        if args.command == 'discover':
            return await discover(context, args.url, args.output, args.settle_seconds)
        if args.command == 'collect':
            return await collect(context, items, args.output)
        return await captions(context, root, args)
