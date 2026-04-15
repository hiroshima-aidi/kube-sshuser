import os
import sys
from typing import Optional


def sanitize_k8s_name(value: str) -> str:
    value = value.lower()
    out = []
    last_dash = False
    for ch in value:
        if ch.isalnum():
            out.append(ch)
            last_dash = False
        else:
            if not last_dash:
                out.append("-")
                last_dash = True
    normalized = "".join(out).strip("-")
    return normalized or "user"


def build_owner() -> str:
    invoking_user = os.environ.get("USER") or os.environ.get("LOGNAME") or "user"
    return sanitize_k8s_name(invoking_user)


def build_pod_name(owner: str, logical_name: Optional[str]) -> str:
    if logical_name:
        return f"gpu-dev-{owner}-{sanitize_k8s_name(logical_name)}"
    return f"gpu-dev-{owner}"


def get_namespace_or_exit() -> str:
    namespace = os.environ.get("K8S_NAMESPACE")
    if not namespace:
        print("K8S_NAMESPACE is required", file=sys.stderr)
        raise SystemExit(1)
    return namespace
