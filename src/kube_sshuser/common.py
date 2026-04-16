#!/usr/bin/env python3

import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from typing import Optional, Sequence, Union


Command = Union[str, Sequence[object]]


def run(cmd: Command, check: bool = True, capture_output: bool = True, input_text: Optional[str] = None):
    if isinstance(cmd, str):
        shell = True
        printable = cmd
    else:
        shell = False
        printable = " ".join(shlex.quote(str(part)) for part in cmd)

    print(f"[cmd] {printable}", file=sys.stderr)
    return subprocess.run(
        cmd,
        text=True,
        check=check,
        capture_output=capture_output,
        input=input_text,
        shell=shell,
    )


def kubectl_get_json(cmd: Sequence[object]):
    result = run(cmd, check=False)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def normalize_name(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    value = value.strip("-")
    if not value:
        raise ValueError("normalized name became empty")
    if len(value) > 63:
        value = value[:63].rstrip("-")
    if not value:
        raise ValueError("normalized name became empty after truncation")
    return value


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def parse_k8s_timestamp(value: Optional[str]):
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def humanize_age(created_at) -> str:
    if created_at is None:
        return "-"

    delta = datetime.now(timezone.utc) - created_at
    total_seconds = max(int(delta.total_seconds()), 0)

    units = [
        (86400, "d"),
        (3600, "h"),
        (60, "m"),
    ]
    for seconds, suffix in units:
        if total_seconds >= seconds:
            return f"{total_seconds // seconds}{suffix}"
    return f"{total_seconds}s"
