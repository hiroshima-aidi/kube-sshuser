#!/usr/bin/env python3

import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from typing import Optional, Sequence


Command = Sequence[object]

OUT_DIR_ENV = "KUBE_SSHUSER_OUT_DIR"
DEFAULT_OUT_DIR = "./output"

_kube_context: Optional[str] = None


class KubectlError(RuntimeError):
    """A kubectl (or other subprocess) invocation exited non-zero."""

    def __init__(self, command: str, returncode: int, stderr: Optional[str] = None):
        self.command = command
        self.returncode = returncode
        self.stderr = (stderr or "").strip()
        detail = f": {self.stderr}" if self.stderr else ""
        super().__init__(f"command failed (exit {returncode}): {command}{detail}")


def default_out_dir() -> str:
    """Base output/registry directory.

    Defaults to $KUBE_SSHUSER_OUT_DIR so the registry does not silently depend on
    the current working directory. Falls back to ./output for backwards compatibility.
    """
    return os.environ.get(OUT_DIR_ENV) or DEFAULT_OUT_DIR


def add_out_dir_argument(parser, help_suffix: str = ""):
    parser.add_argument(
        "--out-dir",
        default=default_out_dir(),
        help=(
            f"base output / registry directory (default: ${OUT_DIR_ENV} or {DEFAULT_OUT_DIR})"
            + help_suffix
        ),
    )


def report_out_dir(out_dir: str):
    from pathlib import Path

    resolved = Path(out_dir).expanduser().resolve()
    source = f"${OUT_DIR_ENV}" if os.environ.get(OUT_DIR_ENV) else "default/--out-dir"
    print(f"[registry] {resolved} ({source})", file=sys.stderr)


def set_kube_context(context: Optional[str]):
    global _kube_context
    _kube_context = context


def add_context_argument(parser):
    parser.add_argument(
        "--context",
        dest="kube_context",
        default=None,
        help="kubectl context to use (default: current context)",
    )


def current_context() -> str:
    if _kube_context:
        return _kube_context
    result = subprocess.run(
        ["kubectl", "config", "current-context"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return "-"
    return result.stdout.strip() or "-"


def _with_context(cmd: Sequence[object]) -> list:
    parts = [str(part) for part in cmd]
    if _kube_context and parts and parts[0] == "kubectl":
        return [parts[0], "--context", _kube_context, *parts[1:]]
    return parts


def run(cmd: Command, check: bool = True, capture_output: bool = True, input_text: Optional[str] = None):
    argv = _with_context(cmd)
    printable = " ".join(shlex.quote(part) for part in argv)

    print(f"[cmd] {printable}", file=sys.stderr)
    result = subprocess.run(
        argv,
        text=True,
        check=False,
        capture_output=capture_output,
        input=input_text,
    )
    if check and result.returncode != 0:
        raise KubectlError(printable, result.returncode, result.stderr)
    return result


def kubectl_get_json(cmd: Sequence[object]):
    result = run(cmd, check=False)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def resource_exists(kind: str, name: str, namespace: Optional[str] = None) -> bool:
    cmd = ["kubectl", "get", kind, name]
    if namespace:
        cmd = ["kubectl", "-n", namespace, "get", kind, name]
    return run(cmd, check=False).returncode == 0


def confirm_or_exit(message: str, assume_yes: bool):
    if assume_yes:
        return
    reply = input(f"{message} [y/N]: ").strip().lower()
    if reply not in {"y", "yes"}:
        print("aborted", file=sys.stderr)
        sys.exit(1)


def confirm_typed_or_exit(expected: str, prompt: str, assume_yes: bool):
    """Require the operator to type an exact string (namespace name) to proceed."""
    if assume_yes:
        return
    reply = input(f"{prompt}\nType '{expected}' to confirm: ").strip()
    if reply != expected:
        print("aborted (input did not match)", file=sys.stderr)
        sys.exit(1)


def cli_main(fn, argv=None):
    """Run a module main() and turn kubectl failures into short error messages."""
    try:
        fn(argv)
    except KubectlError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(exc.returncode or 1)
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        raise SystemExit(130)


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
