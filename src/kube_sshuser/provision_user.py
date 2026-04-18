#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from kube_sshuser.common import normalize_name, normalize_optional_text
from kube_sshuser.provision_kubectl import (
    NODE_PORT_RANGE_END,
    NODE_PORT_RANGE_START,
    collect_observed_namespace_spec,
    find_free_nodeport,
    kubectl_apply,
    kubectl_get_node_ip,
    kubectl_get_node_name_of_pod,
    kubectl_get_pod_name,
    kubectl_wait_deployment,
    resolve_public_key,
)
from kube_sshuser.provision_manifest import build_manifest, parse_image_pull_policy
from kube_sshuser.registry import (
    append_event,
    build_operation_id,
    extract_public_key_metadata,
    load_user_record,
    update_user_record,
    utcnow_iso,
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Provision one namespace + PVC + quota + SA/RBAC + SSH deployment."
    )
    parser.add_argument("--user", required=True, help="logical username, e.g. taro")

    key_group = parser.add_mutually_exclusive_group(required=True)
    key_group.add_argument("--public-key-file", help="path to user's SSH public key file")
    key_group.add_argument("--public-key-string", help="SSH public key string")

    parser.add_argument("--image", required=True, help="SSH pod image")
    parser.add_argument("--name", dest="display_name", help="human-readable name for this user")
    parser.add_argument("--desc", dest="description", help="free-text description for this user")
    parser.add_argument(
        "--pull",
        dest="image_pull_policy",
        default="IfNotPresent",
        type=parse_image_pull_policy,
        help="image pull policy: always / if-not-present / never (default: if-not-present)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="NodePort to use for SSH Service (default: auto-select from 31000-31999)",
    )

    parser.add_argument("--storage", default="100Gi", help="workspace PVC size")
    parser.add_argument("--pvc-name", default="workspace", help="workspace PVC name")
    parser.add_argument("--gpu-quota", type=int, default=1, help="GPU quota for the namespace")
    parser.add_argument("--cpu-quota", default="16", help="CPU quota")
    parser.add_argument("--memory-quota", default="64Gi", help="memory quota")

    parser.add_argument("--ssh-uid", type=int, default=2000, help="UID inside SSH container")
    parser.add_argument("--ssh-gid", type=int, default=2000, help="GID inside SSH container")
    parser.add_argument("--ssh-cpu-request", default="100m", help="ssh pod cpu request")
    parser.add_argument("--ssh-cpu-limit", default="1", help="ssh pod cpu limit")
    parser.add_argument("--ssh-memory-request", default="128Mi", help="ssh pod memory request")
    parser.add_argument("--ssh-memory-limit", default="1Gi", help="ssh pod memory limit")

    parser.add_argument("--namespace", default=None, help="override namespace")
    parser.add_argument("--out-dir", default="./output", help="output directory")
    parser.add_argument(
        "--login-node-label",
        default="role=login-server",
        metavar="KEY=VALUE",
        help="node label selector for the login server node, e.g. role=login-server (default: role=login-server)",
    )
    parser.add_argument(
        "--node-address-type",
        default="ExternalIP",
        choices=["ExternalIP", "InternalIP"],
        help="preferred node address type to report for SSH endpoint",
    )

    return parser.parse_args(argv)



def prepare_args(args):
    args.display_name = normalize_optional_text(args.display_name)
    args.description = normalize_optional_text(args.description)

    args.username = normalize_name(args.user)
    args.namespace = args.namespace or normalize_name(f"ns-{args.username}")
    args.service_account_name = "ssh-user"
    args.role_name = "ssh-user-role"
    args.role_binding_name = "ssh-user-binding"
    args.deployment_name = normalize_name(f"ssh-{args.username}")
    args.service_name = args.deployment_name

    label = args.login_node_label
    if "=" not in label:
        raise SystemExit(f"error: --login-node-label must be in KEY=VALUE format, got: {label!r}")
    args.login_node_label_key, args.login_node_label_value = label.split("=", 1)

    return args


def build_requested_spec(args, node_port: int):
    return {
        "profile": {
            "name": args.display_name,
            "description": args.description,
        },
        "resource_quota": {
            "cpu": args.cpu_quota,
            "memory": args.memory_quota,
            "gpu": args.gpu_quota,
            "storage": args.storage,
            "persistentvolumeclaims": "5",
        },
        "pvc": {
            "name": args.pvc_name,
            "storage": args.storage,
        },
        "ssh_deployment": {
            "image": args.image,
            "image_pull_policy": args.image_pull_policy,
            "node_port": node_port,
            "node_selector": {
                args.login_node_label_key: args.login_node_label_value,
            },
            "resources": {
                "requests": {
                    "cpu": args.ssh_cpu_request,
                    "memory": args.ssh_memory_request,
                },
                "limits": {
                    "cpu": args.ssh_cpu_limit,
                    "memory": args.ssh_memory_limit,
                },
            },
        },
    }


def build_record_payload(
    args,
    operation_id,
    node_ip,
    node_name,
    pod_name,
    public_key,
    requested_spec,
    observed_spec,
    out_dir,
    manifest_path,
    node_port: int,
):
    return {
        "status": "active",
        "last_operation_id": operation_id,
        "profile": {
            "name": args.display_name,
            "description": args.description,
        },
        "ssh": {
            "port": node_port,
            "endpoint": f"{node_ip}:{node_port}" if node_ip else None,
            "host_ip": node_ip,
            "node": node_name,
            "pod": pod_name,
        },
        "ssh_key": extract_public_key_metadata(public_key),
        "namespace": {
            "name": args.namespace,
            "spec": {
                "requested": requested_spec,
                "observed": observed_spec,
            },
        },
        "paths": {
            "output_dir": str(out_dir),
            "manifest_path": str(manifest_path),
        },
    }


def build_summary(args, record_path, events_path, manifest_path, node_ip, node_name, pod_name, node_port: int):
    return {
        "user": args.username,
        "name": args.display_name,
        "description": args.description,
        "namespace": args.namespace,
        "pvc": args.pvc_name,
        "service_account": args.service_account_name,
        "role": args.role_name,
        "role_binding": args.role_binding_name,
        "deployment": args.deployment_name,
        "service": args.service_name,
        "ssh_pod": pod_name,
        "ssh_node": node_name,
        "ssh_host_ip": node_ip,
        "ssh_port": node_port,
        "ssh_endpoint": f"{node_ip}:{node_port}" if node_ip else None,
        "manifest_path": str(manifest_path),
        "registry_record_path": str(record_path),
        "registry_events_path": str(events_path),
        "registry_base_dir": str((Path(args.out_dir).expanduser().resolve() / "_registry")),
        "notes": [
            "SSH pod uses in-cluster ServiceAccount auth; no admin kubeconfig is copied into the pod.",
            "workspace PVC is created but not mounted into the SSH pod to avoid RWO multi-attach issues before RWX/NFS is introduced.",
            "gpu-dev is intended to run as the normal SSH user, not via sudo.",
            "SSH is exposed via NodePort Service; connect to any node IP at the assigned nodePort.",
        ],
    }


MAX_PORT_RETRIES = 5


def main(argv=None):
    args = prepare_args(parse_args(argv))

    existing = load_user_record(args.out_dir, args.username)
    if existing and existing.get("status") == "active":
        print(
            f"error: user '{args.username}' already exists (status: active). "
            "Use 'modify' to update name/description, or 'delete' first.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    public_key = resolve_public_key(args)

    out_dir = (Path(args.out_dir) / args.username).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = (out_dir / f"provision-{args.username}.yaml").resolve()

    # Determine NodePort: explicit --port takes priority, otherwise auto-select with retry
    if args.port is not None:
        node_port = args.port
        manifest = build_manifest(args, public_key, node_port)
        manifest_path.write_text(manifest, encoding="utf-8")
        print("[1/3] applying namespace / pvc / quota / sa / rbac / deployment / service...", file=sys.stderr)
        kubectl_apply(manifest)
    else:
        for attempt in range(MAX_PORT_RETRIES):
            node_port = find_free_nodeport(NODE_PORT_RANGE_START, NODE_PORT_RANGE_END)
            manifest = build_manifest(args, public_key, node_port)
            manifest_path.write_text(manifest, encoding="utf-8")
            print(
                f"[1/3] applying manifest (nodePort={node_port}, attempt {attempt + 1}/{MAX_PORT_RETRIES})...",
                file=sys.stderr,
            )
            try:
                kubectl_apply(manifest)
                break
            except SystemExit:
                if attempt < MAX_PORT_RETRIES - 1:
                    print(f"nodePort {node_port} conflict, retrying...", file=sys.stderr)
                    continue
                raise
        else:
            print(
                f"error: failed to allocate a free NodePort after {MAX_PORT_RETRIES} attempts",
                file=sys.stderr,
            )
            raise SystemExit(1)

    print("[2/3] waiting for ssh deployment rollout...", file=sys.stderr)
    kubectl_wait_deployment(args.namespace, args.deployment_name)

    print("[3/3] collecting endpoint info...", file=sys.stderr)
    pod_name = kubectl_get_pod_name(args.namespace, args.username)
    node_name = kubectl_get_node_name_of_pod(args.namespace, pod_name)
    node_ip = kubectl_get_node_ip(node_name, args.node_address_type)
    operation_id = build_operation_id("create")
    event_time = utcnow_iso()

    requested_spec = build_requested_spec(args, node_port)
    observed_spec = collect_observed_namespace_spec(
        args.namespace, args.pvc_name, args.deployment_name, args.service_name
    )

    record_path, _ = update_user_record(
        args.out_dir,
        args.username,
        build_record_payload(
            args,
            operation_id,
            node_ip,
            node_name,
            pod_name,
            public_key,
            requested_spec,
            observed_spec,
            out_dir,
            manifest_path,
            node_port,
        ),
    )

    events_path = append_event(
        args.out_dir,
        {
            "event_id": operation_id,
            "time": event_time,
            "action": "create",
            "user": args.username,
            "name": args.display_name,
            "description": args.description,
            "status": "active",
            "namespace": args.namespace,
            "ssh_port": node_port,
            "ssh_endpoint": f"{node_ip}:{node_port}" if node_ip else None,
            "manifest_path": str(manifest_path),
        },
    )

    print(
        json.dumps(
            build_summary(args, record_path, events_path, manifest_path, node_ip, node_name, pod_name, node_port),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
