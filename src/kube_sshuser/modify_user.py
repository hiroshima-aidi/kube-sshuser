#!/usr/bin/env python3

import argparse
import json
import sys

from kube_sshuser.common import normalize_name, normalize_optional_text, run
from kube_sshuser.registry import (
    append_event,
    build_operation_id,
    load_user_record,
    update_user_record,
    utcnow_iso,
)

ANNOTATION_NAME = "provision-user.openai.local/display-name"
ANNOTATION_DESC = "provision-user.openai.local/description"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Modify non-disruptive fields of an existing SSH user."
    )
    parser.add_argument("--user", required=True, help="logical username, e.g. taro")
    parser.add_argument("--name", dest="display_name", default=None, help="new human-readable name")
    parser.add_argument("--desc", dest="description", default=None, help="new free-text description")
    parser.add_argument("--gpu-quota", type=int, default=None, help="new GPU quota")
    parser.add_argument("--cpu-quota", default=None, help="new CPU quota, e.g. 16")
    parser.add_argument("--memory-quota", default=None, help="new memory quota, e.g. 64Gi")
    parser.add_argument(
        "--storage",
        default=None,
        help="new PVC size (expand only), e.g. 200Gi",
    )
    parser.add_argument("--pvc-name", default=None, help="PVC name to resize (default: from registry)")
    parser.add_argument("--out-dir", default="./output", help="output directory")
    return parser.parse_args(argv)


def _annotate(namespace: str, resource: str, annotations: dict):
    pairs = [f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in annotations.items()]
    run(["kubectl", "annotate", resource, "-n", namespace, "--overwrite", *pairs], capture_output=False)


def _patch_resource_quota(namespace: str, cpu: str | None, memory: str | None, gpu: int | None):
    hard = {}
    if cpu is not None:
        hard["requests.cpu"] = cpu
        hard["limits.cpu"] = cpu
    if memory is not None:
        hard["requests.memory"] = memory
        hard["limits.memory"] = memory
    if gpu is not None:
        hard["requests.nvidia.com/gpu"] = str(gpu)
        hard["limits.nvidia.com/gpu"] = str(gpu)
    patch = json.dumps({"spec": {"hard": hard}})
    run(
        ["kubectl", "-n", namespace, "patch", "resourcequota", "quota", "--type=merge", "-p", patch],
        capture_output=False,
    )


def _patch_pvc(namespace: str, pvc_name: str, storage: str):
    patch = json.dumps({"spec": {"resources": {"requests": {"storage": storage}}}})
    run(
        ["kubectl", "-n", namespace, "patch", "pvc", pvc_name, "--type=merge", "-p", patch],
        capture_output=False,
    )


def main(argv=None):
    args = parse_args(argv)

    username = normalize_name(args.user)
    record = load_user_record(args.out_dir, username)

    if not record:
        print(f"error: user '{username}' not found in registry (out-dir: {args.out_dir})", file=sys.stderr)
        raise SystemExit(1)

    if record.get("status") != "active":
        print(
            f"error: user '{username}' is not active (status: {record.get('status')}). Cannot modify.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    has_profile = args.display_name is not None or args.description is not None
    has_quota = args.gpu_quota is not None or args.cpu_quota is not None or args.memory_quota is not None
    has_storage = args.storage is not None

    if not has_profile and not has_quota and not has_storage:
        print(
            "error: at least one of --name, --desc, --gpu-quota, --cpu-quota, --memory-quota, --storage must be specified.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    display_name = normalize_optional_text(args.display_name)
    description = normalize_optional_text(args.description)

    namespace = record.get("namespace", {}).get("name")
    deployment_name = normalize_name(f"ssh-{username}")
    operation_id = build_operation_id("modify")
    event_time = utcnow_iso()

    step = 1
    total = sum([has_profile, has_quota, has_storage])

    # --- profile / annotations ---
    annotations = {}
    profile_update = {}

    if args.display_name is not None:
        annotations[ANNOTATION_NAME] = display_name if display_name is not None else ""
        profile_update["name"] = display_name

    if args.description is not None:
        annotations[ANNOTATION_DESC] = description if description is not None else ""
        profile_update["description"] = description

    if annotations:
        print(f"[{step}/{total}] updating annotations on namespace and deployment...", file=sys.stderr)
        _annotate(namespace, f"namespace/{namespace}", annotations)
        _annotate(namespace, f"deployment/{deployment_name}", annotations)
        step += 1

    # --- resource quota ---
    quota_update = {}
    if has_quota:
        print(f"[{step}/{total}] patching ResourceQuota...", file=sys.stderr)
        _patch_resource_quota(namespace, args.cpu_quota, args.memory_quota, args.gpu_quota)
        if args.cpu_quota is not None:
            quota_update["cpu"] = args.cpu_quota
        if args.memory_quota is not None:
            quota_update["memory"] = args.memory_quota
        if args.gpu_quota is not None:
            quota_update["gpu"] = args.gpu_quota
        step += 1

    # --- PVC storage ---
    storage_update = {}
    if has_storage:
        pvc_name = args.pvc_name or (
            record.get("namespace", {}).get("spec", {}).get("requested", {}).get("pvc", {}).get("name")
            or "workspace"
        )
        print(f"[{step}/{total}] patching PVC '{pvc_name}' storage to {args.storage}...", file=sys.stderr)
        _patch_pvc(namespace, pvc_name, args.storage)
        storage_update["pvc_name"] = pvc_name
        storage_update["storage"] = args.storage
        step += 1

    # --- registry update ---
    registry_updates: dict = {"last_operation_id": operation_id}
    if profile_update:
        registry_updates["profile"] = profile_update
    if quota_update:
        registry_updates.setdefault("namespace", {}).setdefault("spec", {}).setdefault(
            "requested", {}
        ).setdefault("resource_quota", {}).update(quota_update)
    if storage_update:
        registry_updates.setdefault("namespace", {}).setdefault("spec", {}).setdefault(
            "requested", {}
        )["pvc"] = {"name": storage_update["pvc_name"], "storage": storage_update["storage"]}

    update_user_record(args.out_dir, username, registry_updates)

    updated_fields = list(profile_update.keys()) + list(quota_update.keys()) + (["storage"] if storage_update else [])

    append_event(
        args.out_dir,
        {
            "event_id": operation_id,
            "time": event_time,
            "action": "modify",
            "user": username,
            "updated_fields": updated_fields,
            "profile": profile_update or None,
            "resource_quota": quota_update or None,
            "storage": storage_update or None,
        },
    )

    print(
        json.dumps(
            {
                "user": username,
                "updated_fields": updated_fields,
                "profile": profile_update or None,
                "resource_quota": quota_update or None,
                "storage": storage_update or None,
                "operation_id": operation_id,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
