#!/usr/bin/env python3
"""Agent-led Yo helpers; no paid generation or playback. Silent previews use stream copy."""
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import unicodedata
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo
import generations
from timeline import compile_timeline

ROOT = Path(__file__).resolve().parents[2]
EXCLUDED = {"node_modules", ".git", "renders", "reviews", "__pycache__", ".cache", "cache"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(paths, settings):
    """Bind reusable frames to their actual inputs and renderer settings."""
    records = []
    for raw in sorted(paths):
        path = Path(raw).resolve(strict=True)
        files = []
        if path.is_dir():
            for directory, folders, names in os.walk(path):
                folders[:] = sorted(name for name in folders if name not in EXCLUDED)
                files.extend(Path(directory) / name for name in sorted(names))
        else:
            files = [path]
        for item in files:
            if not item.is_file() or (path.is_dir() and any(p in EXCLUDED for p in item.relative_to(path).parts)):
                continue
            label = str(item.relative_to(path)) if path.is_dir() else item.name
            records.append([str(path), label, digest(item)])
    if not records:
        raise ValueError("No render inputs to fingerprint")
    payload = json.dumps({"inputs": records, "settings": settings}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def topic_history(root):
    history_path = root / "production/topic-history.json"
    rows = read_json(history_path)["episodes"][:] if history_path.exists() else []
    known = {row["directory"] for row in rows}
    for brief in sorted((root / "episodes").glob("*/brief.md")):
        if brief.parent.name not in known:
            title = next((line.lstrip("# ") for line in brief.read_text().splitlines() if line.startswith("# ")), brief.parent.name)
            rows.append({"directory": brief.parent.name, "topic": title, "repeat_blocked": True})
    for state in sorted((root / "episodes").glob("*/production.json")):
        current = read_json(state)
        row = next((row for row in rows if row["directory"] == state.parent.name), None)
        update = {"directory": state.parent.name, "topic_key": current["topic_key"], "topic": current["topic"], "repeat_blocked": True, "run_state": current["state"]}
        if row is None:
            rows.append(update)
        else:
            row.update(update)
    return rows


def initialize(root, slug, topic_key, topic, duration, direction=None, genre="explainer", premise=None, deadline=None):
    if genre not in {"explainer", "current", "counterfactual", "fiction"}:
        raise ValueError("Unsupported story genre")
    for value in (slug, topic_key):
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError("Use a lowercase hyphenated slug/topic_key")
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Duration must be finite and positive")
    history = topic_history(root)
    if any(row.get("run_state") not in (None, "ready", "failed", "abandoned") for row in history):
        raise ValueError("An unfinished run exists; inspect/resume its production.json before another episode")
    if any(row.get("topic_key") == topic_key for row in history):
        raise ValueError("Topic already reserved or produced; compare aliases/meaning as well")
    defaults = read_json(root / "production/defaults.json")
    frames = round(duration * defaults["fps"])
    if frames < 1 or abs(frames / defaults["fps"] - duration) > 1e-7:
        raise ValueError("Requested duration must fit whole frames")
    stamp = datetime.now(ZoneInfo(defaults["timezone"])).date().isoformat()
    episode = root / "episodes" / f"{stamp}-{slug}"
    episode.mkdir(parents=True, exist_ok=False)
    state = {"topic_key": topic_key, "topic": topic, "direction": direction, "genre": genre,
             "premise": premise, "deadline": deadline, "duration_seconds": duration,
             "total_frames": frames, "fps": defaults["fps"], "state": "planning",
             "created": datetime.now(ZoneInfo(defaults["timezone"])).isoformat(),
             "artifacts": {}, "render_inputs": [], "render_settings": {}, "timeline_file": "timeline.json"}
    (episode / "production.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    return episode


def normalize(text):
    text = unicodedata.normalize("NFC", text).casefold().replace("ё", "е")
    return re.findall(r"\w+", text)


def check_captions(captions, reader, duration):
    if not captions:
        raise ValueError("Captions are missing")
    previous = 0
    for caption in captions:
        start, end = caption["startMs"], caption["endMs"]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (start, end)):
            raise ValueError("Caption times must be finite numbers")
        if not 0 <= start < end <= duration * 1000 + 0.01 or start < previous:
            raise ValueError("Captions overlap or fall outside the video")
        if not caption["text"].strip() or len(caption["text"].splitlines()) > 2:
            raise ValueError("Empty caption or more than two lines")
        previous = end
    if normalize(" ".join(c["text"] for c in captions)) != normalize(reader):
        raise ValueError("Captions do not cover the reader script in order")


def probe(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            check=True, capture_output=True, text=True, timeout=30)
    return json.loads(result.stdout)


def video_hash(path):
    """Hash compressed video packets without decoding, encoding or playing audio."""
    result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0",
                             "-c:v", "copy", "-an", "-f", "streamhash", "-hash", "sha256", "-"],
                            check=True, capture_output=True, text=True, timeout=60)
    value = result.stdout.strip()
    if not re.fullmatch(r"0,v,SHA256=[a-fA-F0-9]{64}", value):
        raise ValueError("Cannot establish video packet identity")
    return value


def make_silent(master, output):
    master, output = Path(master).resolve(strict=True), Path(output).resolve()
    if master == output or output.exists():
        raise ValueError("Silent output must be a new file, separate from master")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-n", "-v", "error", "-i", str(master), "-map", "0:v:0",
                    "-c:v", "copy", "-an", "-movflags", "+faststart", str(output)],
                   check=True, capture_output=True, text=True, timeout=60)
    if any(s["codec_type"] == "audio" for s in probe(output)["streams"]) or video_hash(master) != video_hash(output):
        raise ValueError("Silent output does not match master video")
    return {"silent": str(output), "video_identity": "matched"}


def validate_media(master, silent, duration, fps):
    streams = master["streams"]
    video = [s for s in streams if s["codec_type"] == "video"]
    audio = [s for s in streams if s["codec_type"] == "audio"]
    if len(video) != 1 or not audio:
        raise ValueError("Master must have one video and an audio stream")
    v = video[0]
    if (v["width"], v["height"]) != (1080, 1920) or Fraction(v["avg_frame_rate"]) != fps:
        raise ValueError("Unexpected frame size or frame rate")
    if v.get("codec_name") != "h264" or any(a.get("codec_name") != "aac" for a in audio):
        raise ValueError("Expected H.264/AAC delivery")
    if not math.isfinite(float(master["format"]["duration"])) or abs(float(master["format"]["duration"]) - duration) > 1 / fps + 0.002:
        raise ValueError("Master duration differs from target by more than one frame")
    sv = [s for s in silent["streams"] if s["codec_type"] == "video"]
    if any(s["codec_type"] == "audio" for s in silent["streams"]) or len(sv) != 1:
        raise ValueError("Silent preview must contain video and no audio")
    if (sv[0]["width"], sv[0]["height"]) != (v["width"], v["height"]) or Fraction(sv[0]["avg_frame_rate"]) != fps:
        raise ValueError("Silent preview format differs from master")
    if not math.isfinite(float(silent["format"]["duration"])) or abs(float(silent["format"]["duration"]) - duration) > 1 / fps + 0.002:
        raise ValueError("Silent preview duration differs from target")


def verify(episode):
    episode = Path(episode).resolve()
    state = read_json(episode / "production.json")
    if state.get("user_acceptance") == "rejected":
        raise ValueError("User rejected this delivery; technical checks cannot restore acceptance")
    def artifact(name):
        item = (episode / state["artifacts"][name]).resolve(strict=True)
        if not item.is_relative_to(episode):
            raise ValueError("Delivery artifacts must live inside this episode")
        return item
    master, silent = artifact("master"), artifact("silent")
    if master == silent:
        raise ValueError("Master and silent preview must be different files")
    validate_media(probe(master), probe(silent), state["duration_seconds"], state["fps"])
    if video_hash(master) != video_hash(silent):
        raise ValueError("Silent preview contains a different video from master")
    check_captions(read_json(artifact("captions")), artifact("reader").read_text(), state["duration_seconds"])
    if not artifact("source_dir").is_dir():
        raise ValueError("Editable source directory is missing")
    if state.get("timeline_file"):
        if state["timeline_file"] not in state["render_inputs"]:
            raise ValueError("Include timeline_file explicitly in render_inputs")
        timeline_path = (episode / state["timeline_file"]).resolve(strict=True)
        if not timeline_path.is_relative_to(episode):
            raise ValueError("Timeline must live inside episode")
        timeline = compile_timeline(read_json(timeline_path))
        if timeline["fps"] != state["fps"] or timeline["total_frames"] != state["total_frames"]:
            raise ValueError("Timeline differs from episode target")
    receipt = read_json(episode / "review.json")
    hashes = {name: digest(artifact(name)) for name in ("master", "silent", "captions", "reader")}
    if receipt.get("artifact_hashes") != hashes:
        raise ValueError("Reviews refer to different or changed delivery files")
    if not state["render_inputs"]:
        raise ValueError("Render inputs are not recorded")
    key = fingerprint([str(episode / p) for p in state["render_inputs"]], state["render_settings"])
    if receipt.get("render_key") != key:
        raise ValueError("Sources/settings changed after review")
    for gate in ("facts", "opening", "motion_full", "text_boundaries", "flicker", "audio"):
        entry = receipt.get("checks", {}).get(gate, {})
        if entry.get("status") != "pass" or not entry.get("evidence"):
            raise ValueError("Review incomplete: " + gate)
        evidence = (episode / entry["evidence"]).resolve(strict=True)
        if not evidence.is_relative_to(episode) or not evidence.is_file() or not evidence.stat().st_size:
            raise ValueError("Missing review evidence: " + gate)
    return {"status": "delivery_checks_passed", "hashes": hashes, "render_key": key,
            "limit": "Metadata/text/hashes and recorded reviews checked; this tool cannot itself judge motion, flicker or perceived loudness; pronunciation review is not required."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("context")
    sub.add_parser("preflight")
    init = sub.add_parser("init")
    init.add_argument("--slug", required=True)
    init.add_argument("--topic-key", required=True)
    init.add_argument("--topic", required=True)
    init.add_argument("--duration", type=float)
    init.add_argument("--direction", help="Free-text topic/tone inclination from the user")
    init.add_argument("--genre", choices=["explainer", "current", "counterfactual", "fiction"])
    init.add_argument("--premise", help="Specific user-selected premise; preserve it instead of choosing another topic")
    init.add_argument("--deadline", help="Explicit deadline with date/time/timezone, distinct from video duration")
    key = sub.add_parser("cache-key")
    key.add_argument("paths", nargs="+")
    key.add_argument("--settings", default="{}", help="JSON: renderer/version, fps, resolution, seed, fonts, etc.")
    check = sub.add_parser("verify")
    check.add_argument("episode")
    silent = sub.add_parser("make-silent")
    silent.add_argument("master")
    silent.add_argument("output")
    reserve = sub.add_parser("generation-reserve")
    reserve.add_argument("episode")
    reserve.add_argument("request", help="JSON file with full semantic generation parameters")
    update = sub.add_parser("generation-update")
    update.add_argument("episode")
    update.add_argument("key")
    update.add_argument("--status", required=True, choices=["submitted", "completed", "failed"])
    update.add_argument("--provider-ids", default="{}")
    update.add_argument("--output")
    update.add_argument("--note")
    retry = sub.add_parser("generation-retry")
    retry.add_argument("episode")
    retry.add_argument("key")
    retry.add_argument("--evidence", required=True)
    retry.add_argument("--note", required=True)
    timeline = sub.add_parser("timeline")
    timeline.add_argument("source")
    args = parser.parse_args()
    try:
        if args.command == "context":
            result = {"defaults": read_json(ROOT / "production/defaults.json"), "covered_topics": topic_history(ROOT)}
        elif args.command == "preflight":
            result = {"executables": {name: bool(shutil.which(name)) for name in ("ffmpeg", "ffprobe", "node")},
                      "tts_connector": "must be checked using current MCP tools by the agent; not inferred from old files",
                      "generates_media": False}
        elif args.command == "init":
            duration = args.duration if args.duration is not None else read_json(ROOT / "production/defaults.json")["duration_seconds"]
            genre = args.genre or read_json(ROOT / "production/defaults.json").get("genre", "explainer")
            result = {"episode": str(initialize(ROOT, args.slug, args.topic_key, args.topic, duration, args.direction, genre, args.premise, args.deadline))}
        elif args.command == "cache-key":
            result = {"render_key": fingerprint(args.paths, json.loads(args.settings))}
        elif args.command == "make-silent":
            result = make_silent(args.master, args.output)
        elif args.command == "generation-reserve":
            result = generations.reserve(args.episode, read_json(args.request))
        elif args.command == "generation-update":
            result = generations.update(args.episode, args.key, args.status,
                                        json.loads(args.provider_ids), args.output, args.note)
        elif args.command == "generation-retry":
            result = generations.retry(args.episode, args.key, args.evidence, args.note)
        elif args.command == "timeline":
            result = compile_timeline(read_json(args.source))
        else:
            result = verify(args.episode)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Not ready: {error}\n")


if __name__ == "__main__":
    main()
