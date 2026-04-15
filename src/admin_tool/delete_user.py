#!/usr/bin/env python3

import argparse
import json
import re
import shutil
import shlex
import subprocess
import sys
from pathlib import Path

from admin_tool.registry import append_event, build_operation_id, update_user_record, utcnow_iso


def run(cmd, check=True, capture_output=True):
    if isinstance(cmd, str):
        shell = True
        printable = cmd
    else:
        shell = False
        printable = " ".join(shlex.quote(str(x)) for x in cmd)

    print(f"[cmd] {printable}", file=sys.stderr)
    return subprocess.run(
        cmd,
        text=True,
        check=check,
        capture_output=capture_output,
        shell=shell,
    )


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


def namespace_exists(namespace: str) -> bool:
    result = run(
        ["kubectl", "get", "namespace", namespace],
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def kubectl_delete_namespace(namespace: str) -> bool:
    result = run(
        ["kubectl", "delete", "namespace", namespace],
        check=False,
        capture_output=False,
    )
    return result.returncode == 0


def delete_output_dir(path: Path) -> bool:
    if not path.exists():
        return False
    shutil.rmtree(path)
    return True


def confirm_or_exit(message: str, assume_yes: bool):
    if assume_yes:
        return
    reply = input(f"{message} [y/N]: ").strip().lower()
    if reply not in {"y", "yes"}:
        print("aborted", file=sys.stderr)
        sys.exit(1)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Delete one provisioned SSH user environment."
    )
    p.add_argument("--user", required=True, help="logical username, e.g. taro")
    p.add_argument("--namespace", default=None, help="override namespace")
    p.add_argument("--out-dir", default="./out", help="base output directory")

    p.add_argument(
        "--keep-namespace",
        action="store_true",
        help="do not delete Kubernetes namespace",
    )
    p.add_argument(
        "--keep-files",
        action="store_true",
        help="do not delete out/<user> generated files",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="do not ask for confirmation",
    )
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    username = normalize_name(args.user)
    namespace = args.namespace or normalize_name(f"ns-{username}")
    output_dir = (Path(args.out_dir) / username).resolve()

    summary = {
        "user": username,
        "namespace": namespace,
        "output_dir": str(output_dir),
        "delete_namespace": not args.keep_namespace,
        "delete_files": not args.keep_files,
        "namespace_exists": namespace_exists(namespace) if not args.keep_namespace else None,
        "output_dir_exists": output_dir.exists() if not args.keep_files else None,
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    confirm_or_exit("Proceed with deletion?", args.yes)
    operation_id = build_operation_id("delete")
    started_at = utcnow_iso()

    update_user_record(
        args.out_dir,
        username,
        {
            "status": "deleting",
            "last_operation_id": operation_id,
            "namespace": {"name": namespace},
            "paths": {"output_dir": str(output_dir)},
            "last_delete": {
                "started_at": started_at,
                "keep_namespace": args.keep_namespace,
                "keep_files": args.keep_files,
            },
        },
    )
    append_event(
        args.out_dir,
        {
            "event_id": f"{operation_id}-requested",
            "time": started_at,
            "action": "delete_requested",
            "user": username,
            "namespace": namespace,
            "keep_namespace": args.keep_namespace,
            "keep_files": args.keep_files,
        },
    )

    deleted = {
        "namespace_deleted": None,
        "files_deleted": None,
    }

    if not args.keep_namespace:
        print("[1/2] deleting namespace...", file=sys.stderr)
        deleted["namespace_deleted"] = kubectl_delete_namespace(namespace)

    if not args.keep_files:
        print("[2/2] deleting generated files...", file=sys.stderr)
        deleted["files_deleted"] = delete_output_dir(output_dir)

    completed_at = utcnow_iso()
    if args.keep_namespace:
        final_status = "active"
    else:
        final_status = "deleted" if deleted["namespace_deleted"] else "delete_failed"

    record_updates = {
        "status": final_status,
        "last_operation_id": operation_id,
        "last_delete": {
            "started_at": started_at,
            "completed_at": completed_at,
            "keep_namespace": args.keep_namespace,
            "keep_files": args.keep_files,
            "namespace_deleted": deleted["namespace_deleted"],
            "files_deleted": deleted["files_deleted"],
        },
    }
    if final_status == "deleted":
        record_updates["deleted_at"] = completed_at

    record_path, _ = update_user_record(args.out_dir, username, record_updates)
    events_path = append_event(
        args.out_dir,
        {
            "event_id": f"{operation_id}-completed",
            "time": completed_at,
            "action": "delete_completed",
            "user": username,
            "namespace": namespace,
            "status": final_status,
            "namespace_deleted": deleted["namespace_deleted"],
            "files_deleted": deleted["files_deleted"],
        },
    )

    result = {
        **summary,
        **deleted,
        "registry_record_path": str(record_path),
        "registry_events_path": str(events_path),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()