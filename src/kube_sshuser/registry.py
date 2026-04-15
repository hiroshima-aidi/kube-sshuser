#!/usr/bin/env python3

import base64
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_operation_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _registry_paths(base_out_dir: str):
    base = Path(base_out_dir).expanduser().resolve()
    registry_dir = base / "_registry"
    users_dir = registry_dir / "users"
    events_path = registry_dir / "events.ndjson"
    users_dir.mkdir(parents=True, exist_ok=True)
    return users_dir, events_path


def user_record_path(base_out_dir: str, username: str) -> Path:
    users_dir, _ = _registry_paths(base_out_dir)
    return users_dir / f"{username}.json"


def load_user_record(base_out_dir: str, username: str):
    path = user_record_path(base_out_dir, username)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_user_records(base_out_dir: str):
    users_dir, _ = _registry_paths(base_out_dir)
    records = []
    for path in sorted(users_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if "user" not in record:
            record["user"] = path.stem
        records.append(record)
    return records


def _deep_merge(base: dict, updates: dict):
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def update_user_record(base_out_dir: str, username: str, updates: dict):
    now = utcnow_iso()
    record = load_user_record(base_out_dir, username) or {
        "user": username,
        "created_at": now,
    }
    _deep_merge(record, updates)
    record["updated_at"] = now

    path = user_record_path(base_out_dir, username)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, record


def append_event(base_out_dir: str, event: dict):
    _, events_path = _registry_paths(base_out_dir)
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return events_path


def extract_public_key_metadata(public_key: str):
    parts = public_key.strip().split()
    if len(parts) < 2:
        return {
            "type": None,
            "comment": None,
            "fingerprint_sha256": None,
        }

    key_type = parts[0]
    key_b64 = parts[1]
    comment = " ".join(parts[2:]) if len(parts) > 2 else ""

    pad_len = (-len(key_b64)) % 4
    padded = key_b64 + ("=" * pad_len)

    fingerprint = None
    try:
        raw = base64.b64decode(padded, validate=True)
        digest = hashlib.sha256(raw).digest()
        fp_b64 = base64.b64encode(digest).decode("ascii").rstrip("=")
        fingerprint = f"SHA256:{fp_b64}"
    except Exception:
        fingerprint = None

    return {
        "type": key_type,
        "comment": comment,
        "fingerprint_sha256": fingerprint,
    }
