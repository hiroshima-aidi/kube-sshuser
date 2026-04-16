#!/usr/bin/env python3

import argparse
import json

from kube_sshuser.common import humanize_age, parse_k8s_timestamp, run


MANAGED_BY_LABEL = "app.kubernetes.io/managed-by=provision-user"
DISPLAY_NAME_ANNOTATION = "provision-user.openai.local/display-name"
DESCRIPTION_ANNOTATION = "provision-user.openai.local/description"


def kubectl_get_json(cmd):
    result = run(cmd, check=False)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "kubectl command failed"
        raise RuntimeError(message)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("failed to decode kubectl JSON output") from exc


def format_quantity(requests, limits, resource_name):
    request_value = (requests or {}).get(resource_name)
    limit_value = (limits or {}).get(resource_name)
    if request_value and limit_value:
        return f"{request_value}/{limit_value}"
    return request_value or limit_value or "-"


def format_gpu_quantity(requests, limits):
    request_value = (requests or {}).get("nvidia.com/gpu")
    limit_value = (limits or {}).get("nvidia.com/gpu")
    if request_value and limit_value and request_value == limit_value:
        return request_value
    if request_value and limit_value:
        return f"{request_value}/{limit_value}"
    return request_value or limit_value or "0"


def pod_status(pod):
    phase = pod.get("status", {}).get("phase") or "Unknown"
    container_statuses = pod.get("status", {}).get("containerStatuses") or []
    if any(status.get("state", {}).get("waiting") for status in container_statuses):
        waiting = next(
            (
                status["state"]["waiting"].get("reason")
                for status in container_statuses
                if status.get("state", {}).get("waiting")
            ),
            None,
        )
        return waiting or phase
    if any(status.get("state", {}).get("terminated") for status in container_statuses):
        terminated = next(
            (
                status["state"]["terminated"].get("reason")
                for status in container_statuses
                if status.get("state", {}).get("terminated")
            ),
            None,
        )
        return terminated or phase
    ready_count = sum(1 for status in container_statuses if status.get("ready"))
    if container_statuses and ready_count != len(container_statuses):
        return f"{phase} ({ready_count}/{len(container_statuses)} Ready)"
    return phase


def extract_pod_resources(pod):
    containers = pod.get("spec", {}).get("containers") or []
    if not containers:
        return {"gpu": "-", "cpu": "-", "mem": "-"}

    requests = {}
    limits = {}
    for container in containers:
        resources = container.get("resources") or {}
        container_requests = resources.get("requests") or {}
        container_limits = resources.get("limits") or {}
        for name, value in container_requests.items():
            requests[name] = add_quantities(requests.get(name), value)
        for name, value in container_limits.items():
            limits[name] = add_quantities(limits.get(name), value)

    return {
        "gpu": format_gpu_quantity(requests, limits),
        "cpu": format_quantity(requests, limits, "cpu"),
        "mem": format_quantity(requests, limits, "memory"),
    }


def add_quantities(existing, new_value):
    if existing is None:
        return new_value
    if existing == new_value:
        return existing
    return f"{existing}+{new_value}"


def collect_status_groups():
    namespaces = kubectl_get_json(
        [
            "kubectl",
            "get",
            "namespaces",
            "-l",
            MANAGED_BY_LABEL,
            "-o",
            "json",
        ]
    )
    pods = kubectl_get_json(
        [
            "kubectl",
            "get",
            "pods",
            "-A",
            "-l",
            MANAGED_BY_LABEL,
            "-o",
            "json",
        ]
    )

    pods_by_namespace = {}
    for pod in pods.get("items", []):
        namespace = pod.get("metadata", {}).get("namespace")
        if not namespace:
            continue
        pods_by_namespace.setdefault(namespace, []).append(pod)

    groups = []
    for namespace in namespaces.get("items", []):
        namespace_name = namespace.get("metadata", {}).get("name", "-")
        namespace_age = humanize_age(
            parse_k8s_timestamp(namespace.get("metadata", {}).get("creationTimestamp"))
        )
        namespace_pods = sorted(
            pods_by_namespace.get(namespace_name, []),
            key=lambda item: item.get("metadata", {}).get("name", ""),
        )

        pod_rows = []
        if not namespace_pods:
            pod_rows.append(
                {
                    "name": "-",
                    "status": "NoPods",
                    "age": namespace_age,
                    "node": "-",
                    "gpu": "0",
                    "cpu": "-",
                    "mem": "-",
                }
            )
        else:
            for pod in namespace_pods:
                resources = extract_pod_resources(pod)
                pod_rows.append(
                    {
                        "name": pod.get("metadata", {}).get("name", "-"),
                        "status": pod_status(pod),
                        "age": humanize_age(
                            parse_k8s_timestamp(pod.get("metadata", {}).get("creationTimestamp"))
                        ),
                        "node": pod.get("spec", {}).get("nodeName") or "-",
                        "gpu": resources["gpu"],
                        "cpu": resources["cpu"],
                        "mem": resources["mem"],
                    }
                )

        groups.append(
            {
                "namespace": namespace_name,
                "age": namespace_age,
                "display_name": namespace.get("metadata", {}).get("annotations", {}).get(
                    DISPLAY_NAME_ANNOTATION
                ),
                "description": namespace.get("metadata", {}).get("annotations", {}).get(
                    DESCRIPTION_ANNOTATION
                ),
                "pods": pod_rows,
            }
        )

    return groups


def render_table(rows):
    headers = ["NAME", "STATUS", "AGE", "NODE", "GPU", "CPU", "MEM"]
    keys = ["name", "status", "age", "node", "gpu", "cpu", "mem"]

    widths = []
    for header, key in zip(headers, keys):
        cell_width = max([len(header), *(len(str(row.get(key, "-"))) for row in rows)] or [len(header)])
        widths.append(cell_width)

    lines = [
        "  ".join(header.ljust(width) for header, width in zip(headers, widths)),
        "  ".join("-" * width for width in widths),
    ]
    for row in rows:
        lines.append(
            "  ".join(str(row.get(key, "-")).ljust(width) for key, width in zip(keys, widths))
        )
    return "\n".join(lines)


def render_groups(groups):
    rendered = []
    for group in groups:
        heading = group["namespace"]
        display_name = group.get("display_name")
        description = group.get("description")
        
        # Build the heading with display_name and/or description
        if display_name or description:
            heading_parts = [heading]
            if display_name:
                heading_parts.append(display_name)
            if description:
                heading_parts.append(description)
            heading = " | ".join(heading_parts)
        
        rendered.append(heading)
        rendered.append(render_table(group["pods"]))
    return "\n\n".join(rendered)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Show managed namespaces and pods with status and resource columns."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print raw JSON instead of a formatted table",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    groups = collect_status_groups()

    if args.json:
        print(json.dumps(groups, ensure_ascii=False, indent=2))
        return

    if not groups:
        print("no managed namespaces found")
        return

    print(render_groups(groups))


if __name__ == "__main__":
    main()