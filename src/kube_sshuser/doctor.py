#!/usr/bin/env python3
"""Cross-check the local registry against the cluster.

The registry (``--out-dir``) and the cluster drift apart whenever a namespace is
edited or deleted by hand, or an admin ran create/delete against a different
registry. ``kube-sshuser doctor`` makes that visible instead of letting ``list``
and ``status`` quietly disagree.
"""

import argparse
import json
import sys

from kube_sshuser.common import (
    add_context_argument,
    add_out_dir_argument,
    cli_main,
    current_context,
    kubectl_get_json,
    normalize_name,
    report_out_dir,
    set_kube_context,
)
from kube_sshuser.provision_kubectl import collect_observed_namespace_spec
from kube_sshuser.registry import list_user_records

MANAGED_NAMESPACE_LABEL = "app.kubernetes.io/managed-by=provision-user"

# verdicts, worst first
MISSING = "missing-in-cluster"
ORPHAN = "orphan-namespace"
UNTRACKED = "untracked-namespace"
DRIFT = "drift"
OK = "ok"

SEVERITY = {MISSING: 0, ORPHAN: 1, UNTRACKED: 2, DRIFT: 3, OK: 4}


def managed_namespaces():
    data = kubectl_get_json(
        ["kubectl", "get", "namespace", "-l", MANAGED_NAMESPACE_LABEL, "-o", "json"]
    )
    if data is None:
        return None
    return {
        item.get("metadata", {}).get("name")
        for item in data.get("items", [])
        if item.get("metadata", {}).get("name")
    }


def _requested(record):
    return record.get("namespace", {}).get("spec", {}).get("requested", {})


def compare_spec(record, observed):
    """Fields where the recorded intent no longer matches the cluster."""
    requested = _requested(record)
    quota = requested.get("resource_quota", {})
    pvc = requested.get("pvc", {})
    ssh = requested.get("ssh_deployment", {})

    hard = observed.get("resource_quota_hard") or {}
    diffs = []

    def check(field, want, got):
        if want is None or got is None:
            return
        if str(want) != str(got):
            diffs.append({"field": field, "requested": str(want), "observed": str(got)})

    check("cpu_quota", quota.get("cpu"), hard.get("limits.cpu"))
    check("memory_quota", quota.get("memory"), hard.get("limits.memory"))
    check("gpu_quota", quota.get("gpu"), hard.get("limits.nvidia.com/gpu"))
    check("pvc_storage", pvc.get("storage"), observed.get("pvc_requested_storage"))
    check("node_port", ssh.get("node_port"), observed.get("service_node_port"))

    deployment = observed.get("deployment") or {}
    check("image", ssh.get("image"), deployment.get("image"))

    return diffs


def inspect_record(record, existing_namespaces):
    user = record.get("user")
    status = record.get("status")
    namespace = record.get("namespace", {}).get("name") or normalize_name(f"ns-{user}")
    exists = namespace in existing_namespaces

    row = {
        "user": user,
        "namespace": namespace,
        "registry_status": status,
        "namespace_exists": exists,
        "verdict": OK,
        "detail": "",
        "diffs": [],
    }

    if status == "active" and not exists:
        row["verdict"] = MISSING
        row["detail"] = "registry says active but the namespace is gone from the cluster"
        return row

    if status in {"deleted", "delete_failed"} and exists:
        row["verdict"] = ORPHAN
        row["detail"] = f"registry says {status} but the namespace still exists"
        return row

    if status != "active":
        row["detail"] = f"registry status: {status}"
        return row

    requested = _requested(record)
    pvc_name = requested.get("pvc", {}).get("name") or "workspace"
    deployment_name = normalize_name(f"ssh-{user}")
    observed = collect_observed_namespace_spec(namespace, pvc_name, deployment_name, deployment_name)

    diffs = compare_spec(record, observed)
    if diffs:
        row["verdict"] = DRIFT
        row["diffs"] = diffs
        row["detail"] = ", ".join(f"{d['field']}: {d['requested']} -> {d['observed']}" for d in diffs)
    return row


def build_report(out_dir):
    existing = managed_namespaces()
    if existing is None:
        raise SystemExit("error: could not list managed namespaces (is kubectl working?)")

    records = list_user_records(out_dir)
    rows = [inspect_record(record, existing) for record in records]

    tracked = {row["namespace"] for row in rows}
    for namespace in sorted(existing - tracked):
        rows.append(
            {
                "user": "-",
                "namespace": namespace,
                "registry_status": "-",
                "namespace_exists": True,
                "verdict": UNTRACKED,
                "detail": "managed namespace with no registry record (wrong --out-dir?)",
                "diffs": [],
            }
        )

    rows.sort(key=lambda r: (SEVERITY.get(r["verdict"], 9), r["namespace"]))
    return rows


def render_table(rows):
    headers = ["VERDICT", "USER", "NAMESPACE", "REGISTRY", "DETAIL"]
    body = [
        [
            row["verdict"],
            str(row["user"]),
            row["namespace"],
            str(row["registry_status"]),
            row["detail"] or "-",
        ]
        for row in rows
    ]
    widths = [
        max(len(headers[i]), *(len(r[i]) for r in body)) if body else len(headers[i])
        for i in range(len(headers))
    ]
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    for r in body:
        lines.append("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))).rstrip())
    return "\n".join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Cross-check the local registry against the cluster."
    )
    add_out_dir_argument(parser)
    add_context_argument(parser)
    parser.add_argument("--json", action="store_true", help="print raw JSON instead of a table")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    set_kube_context(args.kube_context)
    report_out_dir(args.out_dir)

    rows = build_report(args.out_dir)

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(f"context: {current_context()}")
        if not rows:
            print("no user records and no managed namespaces found")
        else:
            print(render_table(rows))

    problems = [row for row in rows if row["verdict"] != OK]
    if problems:
        print(f"\n{len(problems)} issue(s) found", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    cli_main(main)
