#!/usr/bin/env python3

import argparse
import json

from kube_sshuser.common import humanize_age, parse_k8s_timestamp, run
from kube_sshuser.registry import list_user_records


MANAGED_NAMESPACE_LABEL = "app.kubernetes.io/managed-by=provision-user"
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


def normalize_cpu_value(cpu_str):
    """Convert CPU value to normalized decimal format (e.g., '100m' -> '0.1', '1' -> '1')"""
    if not cpu_str:
        return None
    cpu_str = str(cpu_str).strip()
    
    # Handle adding quantities like "100m+100m"
    if "+" in cpu_str:
        parts = cpu_str.split("+")
        try:
            total_millicores = 0
            for part in parts:
                part = part.strip()
                if part.endswith("m"):
                    total_millicores += int(part[:-1])
                else:
                    # Convert core format to millicores, add, convert back
                    total_millicores += int(float(part) * 1000)
            cores = total_millicores / 1000
            if cores == int(cores):
                return str(int(cores))
            return f"{cores:.10g}"
        except (ValueError, ZeroDivisionError):
            return cpu_str
    
    if cpu_str.endswith("m"):
        # millicores to cores: 100m -> 0.1
        try:
            millicores = int(cpu_str[:-1])
            cores = millicores / 1000
            # Format nicely: 0.1, 0.5, 1, 2 (remove unnecessary decimals)
            if cores == int(cores):
                return str(int(cores))
            return f"{cores:.10g}"  # Remove trailing zeros
        except ValueError:
            return cpu_str
    else:
        # Already in core format, just clean it up
        try:
            cores = float(cpu_str)
            if cores == int(cores):
                return str(int(cores))
            return f"{cores:.10g}"
        except ValueError:
            return cpu_str


def format_quantity(requests, limits, resource_name):
    request_value = (requests or {}).get(resource_name)
    limit_value = (limits or {}).get(resource_name)
    
    # Special handling for CPU: normalize to decimal format
    if resource_name == "cpu":
        if request_value:
            request_value = normalize_cpu_value(request_value)
        if limit_value:
            limit_value = normalize_cpu_value(limit_value)
    
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


def collect_status_groups(out_dir="./output"):
    # Load port information from registry
    port_by_namespace = {}
    try:
        records = list_user_records(out_dir)
        for record in records:
            namespace = record.get("namespace", {}).get("name")
            port = record.get("ssh", {}).get("port")
            if namespace and port:
                port_by_namespace[namespace] = port
    except Exception:
        # If registry is not available, continue without port info
        pass
    
    namespaces = kubectl_get_json(
        [
            "kubectl",
            "get",
            "namespaces",
            "-l",
            MANAGED_NAMESPACE_LABEL,
            "-o",
            "json",
        ]
    )
    managed_namespace_names = {
        item.get("metadata", {}).get("name")
        for item in namespaces.get("items", [])
        if item.get("metadata", {}).get("name")
    }
    pods = kubectl_get_json(
        [
            "kubectl",
            "get",
            "pods",
            "-A",
            "-o",
            "json",
        ]
    )

    pods_by_namespace = {}
    for pod in pods.get("items", []):
        namespace = pod.get("metadata", {}).get("namespace")
        if not namespace or namespace not in managed_namespace_names:
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
        port = port_by_namespace.get(namespace_name, "-")
        
        if not namespace_pods:
            pod_rows.append(
                {
                    "name": "-",
                    "status": "NoPods",
                    "age": namespace_age,
                    "node": "-",
                    "port": port,
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
                        "port": port,
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
    headers = ["NAME", "STATUS", "AGE", "NODE", "PORT", "GPU", "CPU", "MEM"]
    keys = ["name", "status", "age", "node", "port", "gpu", "cpu", "mem"]

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
    parser.add_argument(
        "--out-dir",
        default="./output",
        help="base output directory for registry (default: ./output)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    groups = collect_status_groups(args.out_dir)

    if args.json:
        print(json.dumps(groups, ensure_ascii=False, indent=2))
        return

    if not groups:
        print("no managed namespaces found")
        return

    print(render_groups(groups))


if __name__ == "__main__":
    main()