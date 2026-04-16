#!/usr/bin/env python3

import argparse
import json
import sys

from kube_sshuser.common import run


MANAGED_NAMESPACE_LABEL_KEY = "app.kubernetes.io/managed-by"
MANAGED_NAMESPACE_LABEL_VALUE = "provision-user"


def kubectl_get_json(cmd):
    result = run(cmd, check=False)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "kubectl command failed"
        raise RuntimeError(message)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("failed to decode kubectl JSON output") from exc


def confirm_or_exit(message, assume_yes):
    if assume_yes:
        return
    reply = input(f"{message} [y/N]: ").strip().lower()
    if reply not in {"y", "yes"}:
        print("aborted", file=sys.stderr)
        raise SystemExit(1)


def get_namespace(namespace):
    return kubectl_get_json(["kubectl", "get", "namespace", namespace, "-o", "json"])


def get_namespace_pods(namespace):
    data = kubectl_get_json(["kubectl", "get", "pods", "-n", namespace, "-o", "json"])
    return data.get("items", [])


def is_managed_namespace(namespace_obj):
    labels = namespace_obj.get("metadata", {}).get("labels") or {}
    return labels.get(MANAGED_NAMESPACE_LABEL_KEY) == MANAGED_NAMESPACE_LABEL_VALUE


def describe_owner_references(pod):
    refs = pod.get("metadata", {}).get("ownerReferences") or []
    owners = []
    for ref in refs:
        kind = ref.get("kind") or "Unknown"
        name = ref.get("name") or "-"
        owners.append(f"{kind}/{name}")
    return owners


def build_target_pods(namespace, pod_name, delete_all):
    pods = get_namespace_pods(namespace)
    if delete_all:
        return pods
    for pod in pods:
        if pod.get("metadata", {}).get("name") == pod_name:
            return [pod]
    return []


def delete_pod(namespace, pod_name, force, grace_period):
    cmd = ["kubectl", "delete", "pod", pod_name, "-n", namespace]
    if grace_period is not None:
        cmd += ["--grace-period", str(grace_period)]
    if force:
        cmd.append("--force")
    result = run(cmd, check=False)
    return {
        "pod": pod_name,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "deleted": result.returncode == 0,
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Delete one pod, or all pods, in a managed namespace."
    )
    parser.add_argument("--namespace", required=True, help="managed namespace name")
    parser.add_argument("--pod", default=None, help="pod name to delete")
    parser.add_argument(
        "--all",
        action="store_true",
        help="delete all pods in the namespace",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="force delete with grace-period 0 unless overridden",
    )
    parser.add_argument(
        "--grace-period",
        type=int,
        default=None,
        help="override termination grace period in seconds",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="do not ask for confirmation",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print JSON result",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.all == (args.pod is not None):
        print("specify exactly one of --all or a pod name", file=sys.stderr)
        raise SystemExit(1)

    namespace_obj = get_namespace(args.namespace)
    if not is_managed_namespace(namespace_obj):
        print(
            f"namespace is not managed by {MANAGED_NAMESPACE_LABEL_VALUE}: {args.namespace}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    effective_grace_period = args.grace_period
    if args.force and effective_grace_period is None:
        effective_grace_period = 0

    targets = build_target_pods(args.namespace, args.pod, args.all)
    if not targets:
        selector = "all pods" if args.all else f"pod {args.pod}"
        print(f"no matching targets found for {selector} in namespace {args.namespace}", file=sys.stderr)
        raise SystemExit(1)

    summary = {
        "namespace": args.namespace,
        "target_count": len(targets),
        "force": args.force,
        "grace_period": effective_grace_period,
        "targets": [
            {
                "pod": pod.get("metadata", {}).get("name", "-"),
                "owners": describe_owner_references(pod),
                "controller_managed": bool(describe_owner_references(pod)),
                "phase": pod.get("status", {}).get("phase") or "Unknown",
            }
            for pod in targets
        ],
        "note": "controller-managed pods are usually recreated automatically after deletion",
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    confirm_or_exit("Proceed with pod deletion?", args.yes)

    results = []
    for pod in targets:
        pod_name = pod.get("metadata", {}).get("name", "-")
        results.append(delete_pod(args.namespace, pod_name, args.force, effective_grace_period))

    payload = {**summary, "results": results}
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if not all(item.get("deleted") for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()