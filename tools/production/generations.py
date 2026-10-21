"""Local reservation ledger. Provider calls remain explicit MCP operations by the agent."""
import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


@contextmanager
def ledger(episode):
    episode = Path(episode).resolve(strict=True)
    if not (episode / "production.json").is_file():
        raise ValueError("Reserve generations only inside an initialized episode")
    with (episode / ".generations.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = episode / "generations.json"
        rows = json.loads(path.read_text()) if path.exists() else {}
        yield episode, rows
        fd, temporary = tempfile.mkstemp(dir=episode, prefix=".generations-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(rows, output, ensure_ascii=False, indent=2, allow_nan=False)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def file_hash(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def reserve(episode, request):
    """Only the first reservation may submit; even an ambiguous reservation blocks resubmission."""
    if request.get("generations_count") != 1 or isinstance(request.get("generations_count"), bool):
        raise ValueError("Set generations_count explicitly to 1")
    if not request.get("model_id") or not request.get("prompt") or request.get("kind") not in {"tts", "sfx", "music", "image", "video", "transcription", "model3d", "rig"}:
        raise ValueError("Request needs kind, model_id and prompt")
    if request["kind"] == "tts":
        defaults = json.loads((Path(__file__).resolve().parents[2] / "production/defaults.json").read_text())
        if request.get("voice_id") != defaults["voice_id"] or request["model_id"] != defaults["tts_model"]:
            raise ValueError("TTS must use the project's configured voice/model")
    if any(key in request for key in ("flow_id", "view_state_id", "estimate_only")):
        raise ValueError("Keep transport IDs/estimates outside semantic generation parameters")
    payload = json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False)
    key = hashlib.sha256(payload.encode()).hexdigest()
    with ledger(episode) as (folder, rows):
        if key in rows:
            row = rows[key]
            action = "inspect_existing"
            if row["status"] == "completed":
                output = (folder / row["output"]).resolve(strict=True)
                if not output.is_relative_to(folder) or file_hash(output) != row["output_hash"]:
                    raise ValueError("Completed generation file changed; inspect, do not regenerate blindly")
                action = "reuse"
            return {"key": key, "action": action, **{k: row[k] for k in ("status", "provider_ids", "output") if k in row}}
        rows[key] = {"request": request, "status": "reserved", "provider_ids": {},
                     "created": datetime.now(timezone.utc).isoformat()}
        return {"key": key, "action": "submit_once", "status": "reserved"}


def update(episode, key, status, provider_ids=None, output=None, note=None):
    if status not in {"submitted", "completed", "failed"}:
        raise ValueError("Unsupported generation status")
    with ledger(episode) as (folder, rows):
        row = rows[key]
        if row["status"] in {"completed", "failed"}:
            raise ValueError("Terminal generation is immutable; inspect it before a deliberate new attempt")
        ids = provider_ids or {}
        if not isinstance(ids, dict) or any(not isinstance(v, str) or not v.strip() for v in ids.values()):
            raise ValueError("Provider IDs must be nonempty strings")
        if any(k in row["provider_ids"] and row["provider_ids"][k] != v for k, v in ids.items()):
            raise ValueError("Provider identity cannot change for a reservation")
        merged = {**row["provider_ids"], **ids}
        if status in {"submitted", "completed"} and not merged:
            raise ValueError("Record the actual provider task/flow/session ID")
        if status == "failed" and not note:
            raise ValueError("Record the confirmed failure and recovery method")
        if status == "completed":
            if not output:
                raise ValueError("Completed generation needs its downloaded output")
            path = (folder / output).resolve(strict=True)
            if not path.is_relative_to(folder) or not path.is_file() or not path.stat().st_size:
                raise ValueError("Output must be a nonempty local episode file")
            row.update(output=str(path.relative_to(folder)), output_hash=file_hash(path))
        row.update(status=status, provider_ids=merged, note=note)
        return {"key": key, "status": status, "provider_ids": merged}


def retry(episode, key, evidence, note):
    """An intentional retry requires a confirmed terminal failure, never merely a timeout."""
    with ledger(episode) as (folder, rows):
        row = rows[key]
        path = (folder / evidence).resolve(strict=True)
        if row["status"] != "failed" or not note or not path.is_relative_to(folder) or not path.is_file() or not path.stat().st_size:
            raise ValueError("Retry requires confirmed failure evidence inside episode and a recovery note")
        history = row.get("attempts", [])
        history.append({k: v for k, v in row.items() if k not in {"request", "attempts"}})
        rows[key] = {"request": row["request"], "status": "reserved", "provider_ids": {},
                     "created": datetime.now(timezone.utc).isoformat(), "attempts": history,
                     "retry_evidence": str(path.relative_to(folder)), "retry_note": note}
        return {"key": key, "action": "submit_once", "attempt": len(history) + 1}
