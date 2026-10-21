import importlib.util
import json
import tempfile
import unittest
import sys
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path

spec = importlib.util.spec_from_file_location("yo", Path(__file__).with_name("yo.py"))
sys.path.insert(0, str(Path(__file__).parent))
yo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(yo)


class ProductionChecks(unittest.TestCase):
    def test_user_rejection_blocks_delivery_even_if_state_is_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            ep = Path(folder)
            (ep / "production.json").write_text(json.dumps({
                "state": "ready", "user_acceptance": "rejected",
            }))
            with patch.object(yo, "probe") as probe:
                with self.assertRaisesRegex(ValueError, "User rejected"):
                    yo.verify(ep)
                probe.assert_not_called()

    def test_cache_changes_on_source_or_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "scene.tsx"
            source.write_text("frame A")
            first = yo.fingerprint([str(source)], {"fps": 30})
            self.assertEqual(first, yo.fingerprint([str(source)], {"fps": 30}))
            source.write_text("frame B")
            self.assertNotEqual(first, yo.fingerprint([str(source)], {"fps": 30}))
            self.assertNotEqual(yo.fingerprint([str(source)], {"fps": 30}), yo.fingerprint([str(source)], {"fps": 60}))

    def test_caption_gap_in_words_and_overlap_fail(self):
        caps = [{"startMs": 0, "endMs": 500, "text": "Всё хорошо"}, {"startMs": 500, "endMs": 900, "text": "сейчас"}]
        yo.check_captions(caps, "Всё хорошо сейчас.", 1)
        with self.assertRaises(ValueError):
            yo.check_captions(caps, "Всё хорошо пропущено сейчас", 1)
        caps[1]["startMs"] = 450
        with self.assertRaises(ValueError):
            yo.check_captions(caps, "Всё хорошо сейчас", 1)

    def test_wrong_duration_and_audio_in_silent_fail(self):
        master = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920, "avg_frame_rate": "30/1"}, {"codec_type": "audio", "codec_name": "aac"}], "format": {"duration": "60.0"}}
        silent = {"streams": [master["streams"][0]], "format": {"duration": "60.0"}}
        yo.validate_media(master, silent, 60, 30)
        with self.assertRaises(ValueError):
            yo.validate_media(master, silent, 61, 30)
        with self.assertRaises(ValueError):
            yo.validate_media(master, master, 60, 30)

    def test_reserved_topic_survives_brief_creation_and_stops_second_run(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "production").mkdir()
            (root / "production/topic-history.json").write_text('{"episodes":[]}')
            (root / "production/defaults.json").write_text('{"fps":30,"timezone":"Asia/Ho_Chi_Minh"}')
            ep = yo.initialize(root, "test", "test-mechanism", "Test mechanism", 60)
            (ep / "brief.md").write_text("# Test mechanism\n")
            self.assertEqual(yo.topic_history(root)[0]["topic_key"], "test-mechanism")
            with self.assertRaises(ValueError):
                yo.initialize(root, "another", "another-mechanism", "Another", 60)
            state = yo.read_json(ep / "production.json")
            state["state"] = "ready"
            (ep / "production.json").write_text(json.dumps(state))
            with self.assertRaises(ValueError):
                yo.initialize(root, "renamed", "test-mechanism", "Renamed", 60)

    def test_direction_and_alternative_premise_survive_reservation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "production").mkdir()
            (root / "production/topic-history.json").write_text('{"episodes":[]}')
            (root / "production/defaults.json").write_text('{"fps":30,"timezone":"Asia/Ho_Chi_Minh"}')
            premise = "Что, если Белла выбрала Джейкоба, а не Эдварда?"
            ep = yo.initialize(root, "alternative-story", "alternative-story", "Alternative", 60,
                               direction="отношения, провокационно", genre="counterfactual", premise=premise)
            state = yo.read_json(ep / "production.json")
            self.assertEqual(state["premise"], premise)
            self.assertEqual(state["direction"], "отношения, провокационно")
            self.assertEqual(state["genre"], "counterfactual")

    def test_invalid_duration_creates_no_episode(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(ValueError):
                yo.initialize(root, "test", "test", "Test", float("nan"))
            self.assertFalse((root / "episodes").exists())

    def test_delivery_receipt_rejected_after_media_or_source_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            ep = Path(folder)
            (ep / "project").mkdir()
            (ep / "project/scene.tsx").write_text("original scene")
            files = {"master": "master.mp4", "silent": "silent.mp4", "captions": "captions.json", "reader": "reader.txt", "source_dir": "project"}
            (ep / "master.mp4").write_bytes(b"fixture master")
            (ep / "silent.mp4").write_bytes(b"fixture silent")
            (ep / "reader.txt").write_text("Hello")
            (ep / "captions.json").write_text('[{"startMs":0,"endMs":1000,"text":"Hello"}]')
            state = {"artifacts": files, "duration_seconds": 60, "fps": 30, "render_inputs": ["project"], "render_settings": {"renderer": "fixture"}}
            (ep / "production.json").write_text(json.dumps(state))
            (ep / "review.md").write_text("Fixture only; no real video reviewed")
            gates = ["facts", "opening", "motion_full", "text_boundaries", "flicker", "audio"]
            receipt = {"artifact_hashes": {k: yo.digest(ep / files[k]) for k in ("master", "silent", "captions", "reader")},
                       "render_key": yo.fingerprint([str(ep / "project")], state["render_settings"]),
                       "checks": {k: {"status": "pass", "evidence": "review.md"} for k in gates}}
            (ep / "review.json").write_text(json.dumps(receipt))
            video = {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920, "avg_frame_rate": "30/1"}
            def fake_probe(path):
                streams = [video] + ([{"codec_type": "audio", "codec_name": "aac"}] if path.name == "master.mp4" else [])
                return {"streams": streams, "format": {"duration": "60"}}
            with patch.object(yo, "probe", side_effect=fake_probe), patch.object(yo, "video_hash", return_value="fixture-video"):
                self.assertEqual(yo.verify(ep)["status"], "delivery_checks_passed")
                with patch.object(yo, "video_hash", side_effect=["master-video", "other-video"]):
                    with self.assertRaisesRegex(ValueError, "different video"):
                        yo.verify(ep)
                opening = receipt["checks"].pop("opening")
                (ep / "review.json").write_text(json.dumps(receipt))
                with self.assertRaisesRegex(ValueError, "Review incomplete: opening"):
                    yo.verify(ep)
                receipt["checks"]["opening"] = opening
                (ep / "review.json").write_text(json.dumps(receipt))
                (ep / "master.mp4").write_bytes(b"different master")
                with self.assertRaisesRegex(ValueError, "different or changed"):
                    yo.verify(ep)
                (ep / "master.mp4").write_bytes(b"fixture master")
                (ep / "project/scene.tsx").write_text("changed scene")
                with self.assertRaisesRegex(ValueError, "Sources/settings changed"):
                    yo.verify(ep)

    def test_cache_outputs_do_not_invalidate_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scene.tsx").write_text("source")
            first = yo.fingerprint([str(root)], {})
            for name in ("cache", ".cache", "renders", "reviews", "node_modules"):
                (root / name / "nested").mkdir(parents=True)
                (root / name / "nested/output").write_text("generated")
            self.assertEqual(first, yo.fingerprint([str(root)], {}))
            (root / "scene.tsx").write_text("edited")
            self.assertNotEqual(first, yo.fingerprint([str(root)], {}))

    def test_caption_word_boundaries_are_preserved(self):
        with self.assertRaises(ValueError):
            yo.check_captions([{"startMs": 0, "endMs": 500, "text": "По этому"}], "Поэтому", 1)
        yo.check_captions([{"startMs": 0, "endMs": 500, "text": "ВСЁ, хорошо!"}], "Всё хорошо.", 1)

    def test_timeline_events_follow_scene_changes(self):
        data = {"fps": 30, "total_frames": 90, "shots": [{"id": "before", "frames": 30}, {"id": "contact", "frames": 60}],
                "events": [{"id": "impact", "shot": "contact", "offset_frames": 5, "roles": ["action", "foley", "background"]}]}
        self.assertEqual(yo.compile_timeline(data)["events"][0]["frame"], 35)
        data["shots"][0]["frames"] = 40
        data["shots"][1]["frames"] = 50
        self.assertEqual(yo.compile_timeline(data)["events"][0]["frame"], 45)
        data["events"][0]["offset_frames"] = 50
        with self.assertRaises(ValueError):
            yo.compile_timeline(data)

    def test_generation_reservation_reuses_and_blocks_ambiguous_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            ep = Path(folder)
            (ep / "production.json").write_text("{}")
            request = {"kind": "tts", "model_id": "eleven_multilingual_v2", "voice_id": "3EuKHIEZbSzrHGNmdYsx", "prompt": "Тест", "generations_count": 1}
            first = yo.generations.reserve(ep, request)
            self.assertEqual(first["action"], "submit_once")
            self.assertEqual(yo.generations.reserve(ep, request)["action"], "inspect_existing")
            key = first["key"]
            yo.generations.update(ep, key, "submitted", {"flow_id": "real-fixture-id"})
            self.assertEqual(yo.generations.reserve(ep, request)["provider_ids"]["flow_id"], "real-fixture-id")
            (ep / "voice.mp3").write_bytes(b"fixture")
            yo.generations.update(ep, key, "completed", output="voice.mp3")
            self.assertEqual(yo.generations.reserve(ep, request)["action"], "reuse")
            (ep / "voice.mp3").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                yo.generations.reserve(ep, request)
            with self.assertRaises(ValueError):
                yo.generations.reserve(ep, {**request, "generations_count": 4})

    def test_generation_failure_does_not_authorize_automatic_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            ep = Path(folder)
            (ep / "production.json").write_text("{}")
            request = {"kind": "sfx", "model_id": "fixture", "prompt": "contact", "generations_count": 1}
            key = yo.generations.reserve(ep, request)["key"]
            with self.assertRaises(ValueError):
                yo.generations.update(ep, key, "completed", output="missing")
            yo.generations.update(ep, key, "failed", note="Fixture confirmed failed; inspect before recovery")
            self.assertEqual(yo.generations.reserve(ep, request)["action"], "inspect_existing")
            (ep / "failure.txt").write_text("Fixture terminal failure")
            retry = yo.generations.retry(ep, key, "failure.txt", "Fixture intentional recovery")
            self.assertEqual(retry["attempt"], 2)
            self.assertEqual(yo.generations.reserve(ep, request)["action"], "inspect_existing")
            with self.assertRaises(ValueError):
                yo.generations.retry(ep, key, "failure.txt", "Timeout is not a confirmed failure")

    def test_concurrent_generation_reservations_allow_one_submission(self):
        with tempfile.TemporaryDirectory() as folder:
            ep = Path(folder)
            (ep / "production.json").write_text("{}")
            request = {"kind": "sfx", "model_id": "fixture", "prompt": "contact", "generations_count": 1}
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: yo.generations.reserve(ep, request), range(2)))
            self.assertEqual(sorted(r["action"] for r in results), ["inspect_existing", "submit_once"])

    @unittest.skipUnless(shutil.which("node"), "Node not installed")
    def test_common_scene_clock_is_deterministic_at_boundaries(self):
        runtime = Path(__file__).with_name("scene-clock.cjs").resolve()
        data = yo.compile_timeline({"fps": 30, "total_frames": 60,
            "shots": [{"id": "first", "frames": 30}, {"id": "second", "frames": 30}],
            "events": [{"id": "impact", "shot": "second", "offset_frames": 0}]})
        code = "const {sceneClock}=require(process.argv[1]);const t=JSON.parse(process.argv[2]);const c=sceneClock(t,30);if(c.shot.id!=='second'||c.localFrame!==0||c.event('impact').ageFrames!==0)throw Error('clock mismatch');if(sceneClock(t,29).shot.id!=='first')throw Error('boundary');"
        subprocess.run(["node", "-e", code, str(runtime), json.dumps(data)], check=True, capture_output=True, timeout=10)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")
    def test_real_packet_identity_and_silent_remux(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for color in ("red", "blue"):
                subprocess.run(["ffmpeg", "-n", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=32x32:r=10:d=0.3",
                    "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-shortest", "-c:v", "libx264", "-threads", "1",
                    "-preset", "ultrafast", "-c:a", "aac", str(root / f"{color}.mp4")],
                    check=True, capture_output=True, timeout=20)
            silent = root / "silent.mp4"
            yo.make_silent(root / "red.mp4", silent)
            self.assertEqual(yo.video_hash(root / "red.mp4"), yo.video_hash(silent))
            self.assertNotEqual(yo.video_hash(root / "blue.mp4"), yo.video_hash(silent))
            self.assertFalse(any(s["codec_type"] == "audio" for s in yo.probe(silent)["streams"]))
            with self.assertRaises(ValueError):
                yo.make_silent(root / "blue.mp4", silent)



if __name__ == "__main__":
    unittest.main()
