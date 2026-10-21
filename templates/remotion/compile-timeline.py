from pathlib import Path
import json, importlib.util,sys
p=Path(__file__).resolve().parent
root=next((d for d in p.parents if (d/'tools/production/timeline.py').is_file()),None)
if root is None: raise SystemExit('Keep the project inside a multK workshop containing tools/production')
spec=importlib.util.spec_from_file_location('multk_timeline',root/'tools/production/timeline.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
(p/'src/timeline.compiled.json').write_text(json.dumps(module.compile_timeline(json.loads((p/'timeline.json').read_text())),ensure_ascii=False,indent=2)+'\n')
