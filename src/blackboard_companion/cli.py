"""CLI shared by humans and skill-capable agents."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .captions.hls import SubtitleError
from .online import NTU_SITE, run_online
from .pipeline.offline import prepare, validate
from .pipeline import learning


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='bbcompanion')
    sub = parser.add_subparsers(dest='command', required=True)
    doctor = sub.add_parser('doctor', help='check local runtime dependencies')
    doctor.add_argument('--json', action='store_true')
    doctor.add_argument('--data-dir', type=Path)
    run = sub.add_parser('run', help='create a course request and prepare agent analysis')
    run.add_argument('--request', type=Path, required=True)
    run.add_argument('--output', type=Path, required=True)
    for command in ('normalize', 'inspect', 'resume', 'render'):
        child = sub.add_parser(command)
        child.add_argument('--run', type=Path, required=True)
        if command == 'normalize':
            child.add_argument('--input', type=Path)
        if command == 'render':
            child.add_argument('--analysis', type=Path, required=True)
    local = sub.add_parser('prepare', help='experimental local preparation')
    local.add_argument('--input', type=Path, required=True)
    local.add_argument('--output', type=Path, required=True)
    validation = sub.add_parser('validate', help='basic prepared-file checks')
    validation.add_argument('--run', type=Path, required=True)
    for command in ('login', 'discover', 'collect', 'captions', 'browse'):
        child = sub.add_parser(command)
        child.add_argument('--site', default=NTU_SITE)
        child.add_argument('--account', required=True, help='local alias, not a password')
        child.add_argument('--data-dir', type=Path, help='private profile root')
        child.add_argument('--browser', choices=['msedge', 'chrome', 'chromium'], default='msedge')
        if command in ('login', 'captions'):
            child.add_argument('--timeout', type=int, default=600)
        if command != 'login':
            child.add_argument('--output', type=Path, required=True)
        if command in ('discover', 'captions'):
            child.add_argument('--url', required=True)
        if command == 'discover':
            child.add_argument('--settle-seconds', type=float, default=3)
        if command == 'collect':
            child.add_argument('--selection', type=Path, required=True)
        if command == 'captions':
            child.add_argument('--name', required=True, help='stable replay identifier')
            child.add_argument('--caption-asset', help='select an asset if multiple tracks are captured')
            child.add_argument('--timestamps', choices=['auto', 'local', 'absolute'], default='auto')
            child.add_argument('--mpegts-origin', type=float)
    args = parser.parse_args(argv)
    try:
        if args.command == 'doctor':
            from .doctor import diagnose
            result = diagnose(args.data_dir)
        elif args.command == 'run':
            result = learning.start(args.request, args.output)
        elif args.command == 'normalize':
            result = learning.normalize(args.run, args.input)
        elif args.command == 'resume':
            result = learning.normalize(args.run)
        elif args.command == 'inspect':
            result = learning.inspect(args.run)
        elif args.command == 'render':
            result = learning.render(args.run, args.analysis)
        elif args.command == 'prepare':
            result = prepare(args.input, args.output)
        elif args.command == 'validate':
            manifest = args.run / 'manifest.json'
            modern = manifest.exists() and learning.read_json(manifest).get('schema_version') == '1.0'
            result = learning.validate(args.run) if modern else validate(args.run)
            if not modern:
                result['tutorial_complete'] = False
                result['warning'] = 'Legacy preparation validation only; this is not a completed tutorial.'
        elif args.command == 'browse':
            from .browser_session import run_live
            result = asyncio.run(run_live(args))
        else:
            result = asyncio.run(run_online(args))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get('stage') == 'failed' or result.get('valid') is False:
            return 1
        return 2 if result.get('status') in {'needs_revision', 'needs_acquisition', 'needs_normalization'} else 0
    except KeyboardInterrupt:
        print('Cancelled.')
        return 130
    except Exception as exc:
        # Browser/library exception text may contain signed URLs or credentials.
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__,
                          'message': str(exc) if isinstance(exc, (SubtitleError, learning.LearningError)) else
                          'Command failed; check input paths, JSON fields and doctor. Private details omitted.'}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
