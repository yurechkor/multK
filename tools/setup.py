#!/usr/bin/env python3
"""Read-only environment check; explicit timezone update, no generation/playback."""
import argparse
import json
import platform
import shutil
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]

def check():
    executables = {name: shutil.which(name) is not None for name in ('python3','node','npm','ffmpeg','ffprobe')}
    supported = sys.platform != 'win32'
    return {'python': platform.python_version(), 'python_ok': sys.version_info >= (3,11),
            'platform': sys.platform, 'posix_ledger_ok': supported, 'executables': executables,
            'files_ok': all((ROOT/p).is_file() for p in ('AGENTS.md','PROJECT.md','production/defaults.json','.agents/skills/motion-yo/SKILL.md')),
            'connections': 'Agent must inspect current account tools and Nikolay voice separately; not verified here.',
            'generates_media': False, 'plays_audio': False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--timezone', help='IANA timezone, for example Europe/Moscow')
    args=parser.parse_args()
    if args.timezone:
        try: ZoneInfo(args.timezone)
        except ZoneInfoNotFoundError: parser.error('Unknown timezone: '+args.timezone)
        path=ROOT/'production/defaults.json'; data=json.loads(path.read_text(encoding='utf-8'))
        data['timezone']=args.timezone;path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    result=check();print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['python_ok'] and result['posix_ledger_ok'] and result['files_ok'] and all(result['executables'].values()) else 1

if __name__=='__main__': raise SystemExit(main())
