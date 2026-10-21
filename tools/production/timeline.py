"""Compile the single timeline used by scene, sound, background and transition adapters."""
def compile_timeline(data):
    fps, total = data["fps"], data["total_frames"]
    if type(fps) is not int or fps <= 0 or type(total) is not int or total <= 0:
        raise ValueError("Timeline fps/total_frames must be positive integers")
    shots, known, cursor = [], {}, 0
    for shot in data["shots"]:
        name, duration = shot["id"], shot["frames"]
        if not isinstance(name, str) or not name or name in known or type(duration) is not int or duration < 1:
            raise ValueError("Shot IDs must be unique and durations positive whole frames")
        item = {**shot, "from": cursor, "to": cursor + duration}
        known[name] = item
        shots.append(item)
        cursor += duration
    if cursor != total:
        raise ValueError("Shots must cover the target exactly")
    events, names = [], set()
    for event in data.get("events", []):
        name, offset = event["id"], event["offset_frames"]
        shot = known[event["shot"]]
        if not isinstance(name, str) or not name or name in names or type(offset) is not int or not 0 <= offset < shot["frames"]:
            raise ValueError("Event IDs must be unique and offsets inside their shot")
        names.add(name)
        frame = shot["from"] + offset
        events.append({**event, "frame": frame, "seconds": frame / fps})
    return {"fps": fps, "total_frames": total, "shots": shots,
            "events": sorted(events, key=lambda event: (event["frame"], event["id"]))}
