#!/usr/bin/env python3

import argparse
import json
import shutil
import sys
from pathlib import Path

from kube_sshuser.common import (
    add_context_argument,
    add_out_dir_argument,
    cli_main,
    confirm_or_exit,
    confirm_typed_or_exit,
    current_context,
    kubectl_get_json,
    normalize_name,
    report_out_dir,
    run,
    set_kube_context,
)
from kube_sshuser.registry import (
    append_event,
    build_operation_id,
    load_user_record,
    update_user_record,
    utcnow_iso,
)


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


def describe_namespace_contents(namespace: str):
    """Best-effort inventory of what deleting the namespace destroys."""
    pvcs = kubectl_get_json(["kubectl", "-n", namespace, "get", "pvc", "-o", "json"]) or {}
    pods = kubectl_get_json(["kubectl", "-n", namespace, "get", "pods", "-o", "json"]) or {}
    return {
        "pvcs": [
            {
                "name": item.get("metadata", {}).get("name"),
                "storage": item.get("spec", {})
                .get("resources", {})
                .get("requests", {})
                .get("storage"),
            }
            for item in pvcs.get("items", [])
        ],
        "pod_count": len(pods.get("items", [])),
    }


def build_option_parser():
    """Every delete option except the username (shared with cli.py via parents=)."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--namespace",
        default=None,
        help="override namespace (default: from registry, else ns-<user>)",
    )
    add_out_dir_argument(p)
    add_context_argument(p)

    p.add_argument(
        "--keep-namespace",
        action="store_true",
        help="do not delete Kubernetes namespace",
    )
    p.add_argument(
        "--keep-files",
        action="store_true",
        help="do not delete output/<user> generated files",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="do not ask for confirmation",
    )
    return p


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Delete one provisioned SSH user environment.",
        parents=[build_option_parser()],
    )
    p.add_argument("--user", required=True, help="logical username, e.g. taro")
    return p.parse_args(argv)


def resolve_namespace(args, username: str):
    """Namespace to delete, preferring what create actually recorded.

    Guessing ns-<user> is wrong whenever the environment was created with an
    explicit --namespace, and would target an unrelated namespace.
    """
    if args.namespace:
        return args.namespace, "--namespace"

    record = load_user_record(args.out_dir, username)
    recorded = (record or {}).get("namespace", {}).get("name")
    if recorded:
        return recorded, "registry"

    guessed = normalize_name(f"ns-{username}")
    print(
        f"warning: no registry record for '{username}' in {args.out_dir}; "
        f"falling back to guessed namespace '{guessed}'",
        file=sys.stderr,
    )
    return guessed, "guessed"


def main(argv=None):
    run_with_args(parse_args(argv))


def run_with_args(args):
    set_kube_context(args.kube_context)
    report_out_dir(args.out_dir)

    username = normalize_name(args.user)
    namespace, namespace_source = resolve_namespace(args, username)
    output_dir = (Path(args.out_dir) / username).resolve()

    exists = namespace_exists(namespace) if not args.keep_namespace else None

    summary = {
        "user": username,
        "context": current_context(),
        "namespace": namespace,
        "namespace_source": namespace_source,
        "output_dir": str(output_dir),
        "delete_namespace": not args.keep_namespace,
        "delete_files": not args.keep_files,
        "namespace_exists": exists,
        "output_dir_exists": output_dir.exists() if not args.keep_files else None,
    }
    if exists:
        summary["will_destroy"] = describe_namespace_contents(namespace)

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.keep_namespace:
        print("(--keep-namespace: cluster resources are left untouched)", file=sys.stderr)
        confirm_or_exit("Proceed with deletion?", args.yes)
    else:
        confirm_typed_or_exit(
            namespace,
            f"This deletes namespace '{namespace}' in context '{current_context()}' "
            "including its PersistentVolumeClaims. Stored data will be lost and cannot "
            "be recovered.",
            args.yes,
        )
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
    cli_main(main)