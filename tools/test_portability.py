import importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('new_project',ROOT/'tools/new_project.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class Portability(unittest.TestCase):
    def test_new_copy_has_fresh_history_and_can_initialize_episode(self):
        with tempfile.TemporaryDirectory() as temp:
            copy=module.create(Path(temp)/'my workshop')
            self.assertTrue((copy/'.agents/skills/motion-yo/SKILL.md').is_file())
            self.assertFalse((copy/'.git').exists())
            self.assertFalse(any(copy.rglob('node_modules')))
            self.assertEqual(json.loads((copy/'production/topic-history.json').read_text()),{'episodes':[]})
            run=subprocess.run([sys.executable,str(copy/'tools/production/yo.py'),'init','--slug','first-story','--topic-key','first-story','--topic','Первая история','--duration','45'],check=True,text=True,capture_output=True)
            ep=Path(json.loads(run.stdout)['episode']);state=json.loads((ep/'production.json').read_text())
            self.assertEqual(state['total_frames'],1350)
            self.assertTrue(ep.is_relative_to(copy/'episodes'))
            self.assertFalse((ep/'generations.json').exists())
            with self.assertRaises(ValueError):module.create(copy)
    def test_context_runs_without_local_history(self):
        run=subprocess.run([sys.executable,str(ROOT/'tools/production/yo.py'),'context'],check=True,text=True,capture_output=True)
        self.assertEqual(json.loads(run.stdout)['covered_topics'],[])
    def test_single_clock_matches_compiled_event(self):
        if not __import__('shutil').which('node'):self.skipTest('Node not installed')
        code="const {sceneClock}=require('./tools/production/scene-clock.cjs'); const t=require('./templates/remotion/src/timeline.compiled.json'); const c=sceneClock(t,30); if(c.event('contact').ageFrames!==0||c.localFrame!==30)process.exit(1);"
        subprocess.run(['node','-e',code],cwd=ROOT,check=True)
if __name__=='__main__':unittest.main()
