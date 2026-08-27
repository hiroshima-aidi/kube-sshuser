import datetime
import json
import subprocess
import sys
from typing import Optional


def parse_k8s_timestamp(value: str) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


def human_age(creation_timestamp: str) -> str:
    dt = parse_k8s_timestamp(creation_timestamp)
    if not dt:
        return "-"

    now = datetime.datetime.now(datetime.timezone.utc)
    delta = now - dt.astimezone(datetime.timezone.utc)
    seconds = int(delta.total_seconds())

    if seconds < 0:
        return "0s"
    if seconds < 60:
        return f"{seconds}s"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"

    days = hours // 24
    if days < 30:
        return f"{days}d"

    months = days // 30
    if months < 12:
        return f"{months}mo"

    years = days // 365
    return f"{years}y"


def summarize_status(item: dict) -> str:
    metadata = item.get("metadata", {})
    deletion_ts = metadata.get("deletionTimestamp")
    if deletion_ts:
        return "Terminating"

    status = item.get("status", {})
    phase = status.get("phase", "Unknown")
    container_statuses = status.get("containerStatuses") or []

    for cs in container_statuses:
        state = cs.get("state") or {}
        if "waiting" in state:
            reason = state["waiting"].get("reason")
            if reason:
                return reason
        if "terminated" in state:
            reason = state["terminated"].get("reason")
            if reason:
                return reason

    if phase == "Running":
        ready_count = 0
        total_count = len(container_statuses)
        for cs in container_statuses:
            if cs.get("ready"):
                ready_count += 1
        if total_count > 0 and ready_count < total_count:
            return f"NotReady({ready_count}/{total_count})"
        return "Running"

    return phase


def first_container(item: dict) -> dict:
    containers = item.get("spec", {}).get("containers") or []
    if containers:
        return containers[0]
    return {}


def get_gpu(item: dict) -> str:
    ann = item.get("metadata", {}).get("annotations", {})
    if ann.get("gpu-dev/gpu"):
        return ann["gpu-dev/gpu"]

    container = first_container(item)
    limits = container.get("resources", {}).get("limits", {})
    gpu = limits.get("nvidia.com/gpu")
    return str(gpu) if gpu is not None else "-"


def get_cpu(item: dict) -> str:
    ann = item.get("metadata", {}).get("annotations", {})
    cpu_req = ann.get("gpu-dev/cpu-request")
    cpu_lim = ann.get("gpu-dev/cpu-limit")
    if cpu_req or cpu_lim:
        return f"{cpu_req or '-'}/{cpu_lim or '-'}"

    container = first_container(item)
    res = container.get("resources", {})
    req = res.get("requests", {}).get("cpu", "-")
    lim = res.get("limits", {}).get("cpu", "-")
    return f"{req}/{lim}"


def get_mem(item: dict) -> str:
    ann = item.get("metadata", {}).get("annotations", {})
    mem_req = ann.get("gpu-dev/memory-request")
    mem_lim = ann.get("gpu-dev/memory-limit")
    if mem_req or mem_lim:
        return f"{mem_req or '-'}/{mem_lim or '-'}"

    container = first_container(item)
    res = container.get("resources", {})
    req = res.get("requests", {}).get("memory", "-")
    lim = res.get("limits", {}).get("memory", "-")
    return f"{req}/{lim}"


def list_pods(namespace: str, owner: str, env=None):
    result = subprocess.run(
        [
            "kubectl",
            "-n",
            namespace,
            "get",
            "pods",
            "-l",
            f"app=gpu-dev,owner={owner}",
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    if result.returncode != 0:
        print(result.stderr.strip() or "failed to list pods", file=sys.stderr)
        raise SystemExit(result.returncode)

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("failed to parse kubectl output as JSON", file=sys.stderr)
        raise SystemExit(1)

    items = payload.get("items", [])
    if not items:
        print("No gpu-dev pods found.")
        return

    rows = []
    for item in items:
        metadata = item.get("metadata", {})
        spec = item.get("spec", {})

        rows.append(
            {
                "NAME": metadata.get("name", "-"),
                "STATUS": summarize_status(item),
                "AGE": human_age(metadata.get("creationTimestamp", "")),
                "NODE": spec.get("nodeName", "-"),
                "GPU": get_gpu(item),
                "CPU": get_cpu(item),
                "MEM": get_mem(item),
                "_sort_ts": metadata.get("creationTimestamp", ""),
            }
        )

    rows.sort(key=lambda x: x["_sort_ts"])

    headers = ["NAME", "STATUS", "AGE", "NODE", "GPU", "CPU", "MEM"]
    widths = {h: len(h) for h in headers}
    for row in rows:
        for h in headers:
            widths[h] = max(widths[h], len(str(row[h])))

    def fmt(row: dict) -> str:
        return "  ".join(str(row[h]).ljust(widths[h]) for h in headers)

    print(fmt({h: h for h in headers}))
    print("  ".join("-" * widths[h] for h in headers))
    for row in rows:
        print(fmt(row))
