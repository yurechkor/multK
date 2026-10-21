#!/usr/bin/env python3
"""Create a separate workshop with empty history, never copy credentials/media/.git."""
import argparse
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
IGNORED={'.git','node_modules','__pycache__','.cache','cache','renders','build','out'}

def ignore(directory,names):
    return [n for n in names if n in IGNORED or (n.startswith('.env') and n!='.env.example') or n.endswith(('.pyc','.log','.pem','.key','.p12'))]

def create(destination):
    destination=Path(destination).expanduser().resolve()
    if destination.exists(): raise ValueError('Destination already exists; choose a new directory')
    if destination.is_relative_to(ROOT): raise ValueError('Place a new workshop outside this repository')
    destination.mkdir(parents=True)
    for path in ROOT.glob('*.md'): shutil.copy2(path,destination/path.name)
    for name in ('LICENSE','.gitignore','.env.example'):
        if (ROOT/name).is_file(): shutil.copy2(ROOT/name,destination/name)
    for name in ('docs','tools','templates','examples','.agents','.github'):
        if (ROOT/name).is_dir(): shutil.copytree(ROOT/name,destination/name,ignore=ignore)
    (destination/'production').mkdir()
    for name in ('defaults.json','layout-1080x1920.json','topic-history.json.example'):
        if (ROOT/'production'/name).is_file(): shutil.copy2(ROOT/'production'/name,destination/'production'/name)
    (destination/'production/topic-history.json').write_text('{"episodes": []}\n',encoding='utf-8')
    (destination/'episodes').mkdir();shutil.copy2(ROOT/'episodes/README.md',destination/'episodes/README.md')
    return destination

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('destination');args=parser.parse_args()
    try: print(json.dumps({'project':str(create(args.destination)),'generates_media':False},ensure_ascii=False))
    except (ValueError,OSError) as e: parser.exit(1,str(e)+'\n')
