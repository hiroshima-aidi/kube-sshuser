#!/usr/bin/env python3

import argparse
import importlib
import os
import re
import time
from pathlib import Path

from .gpu_dev_core import DEFAULT_CPU_LIMIT
from .gpu_dev_core import DEFAULT_CPU_REQUEST
from .gpu_dev_core import DEFAULT_GPU
from .gpu_dev_core import DEFAULT_IMAGE
from .gpu_dev_core import DEFAULT_MEMORY_LIMIT
from .gpu_dev_core import DEFAULT_MEMORY_REQUEST
from .gpu_dev_core import DEFAULT_MOUNT_PATH
from .gpu_dev_core import DEFAULT_NODE_LABEL_KEY
from .gpu_dev_core import DEFAULT_NODE_LABEL_VALUE
from .gpu_dev_core import DEFAULT_PULL
from .gpu_dev_core import DEFAULT_PVC
from .gpu_dev_core import DEFAULT_RUNTIME_CLASS
from .gpu_dev_core import DEFAULT_TTL
from .gpu_dev_core import build_owner
from .gpu_dev_core import build_pod_name
from .gpu_dev_core import delete_all_pods
from .gpu_dev_core import delete_pod
from .gpu_dev_core import ensure_pod
from .gpu_dev_core import get_namespace_or_exit
from .gpu_dev_core import list_pods
from .gpu_dev_core import run
from .gpu_dev_core import start_port_forward
from .gpu_dev_core import stop_process
from .gpu_dev_core import validate_forwards


def _add_name_argument(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--name",
        default=None,
        help="Logical pod name. Example: --name test1 -> gpu-dev-<owner>-test1",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage interactive GPU dev pods using in-cluster ServiceAccount auth."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    up_parser = subparsers.add_parser("up", help="Create or attach to a gpu-dev pod")
    up_parser.add_argument(
        "--file",
        default=None,
        help="Path to YAML file for gpu-dev up options",
    )
    up_parser.add_argument("--ttl", type=int, default=DEFAULT_TTL, help="Pod lifetime in seconds")
    up_parser.add_argument("--gpu", type=int, default=DEFAULT_GPU, help="Number of GPUs")
    up_parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE,
        help="Container image",
    )
    up_parser.add_argument(
        "--pull",
        type=parse_pull_policy,
        default=DEFAULT_PULL,
        metavar="POLICY",
        help="Image pull policy: always|if-not-present|never (default: if-not-present)",
    )
    _add_name_argument(up_parser)
    up_parser.add_argument("--pvc", default=DEFAULT_PVC, help="PVC name to mount")
    up_parser.add_argument("--mount-path", default=DEFAULT_MOUNT_PATH, help="PVC mount path")
    up_parser.add_argument(
        "--workdir",
        default=None,
        help="Container working directory (defaults to --mount-path)",
    )
    up_parser.add_argument("--runtime-class", default=DEFAULT_RUNTIME_CLASS, help="RuntimeClass name")
    up_parser.add_argument(
        "--node-selector",
        default=None,
        metavar="KEY=VALUE",
        help=(
            "Node selector in KEY=VALUE format "
            f"(default: {DEFAULT_NODE_LABEL_KEY}={DEFAULT_NODE_LABEL_VALUE})"
        ),
    )
    up_parser.add_argument("--cpu-request", default=DEFAULT_CPU_REQUEST, help="CPU request")
    up_parser.add_argument("--cpu-limit", default=DEFAULT_CPU_LIMIT, help="CPU limit")
    up_parser.add_argument("--memory-request", default=DEFAULT_MEMORY_REQUEST, help="Memory request")
    up_parser.add_argument("--memory-limit", default=DEFAULT_MEMORY_LIMIT, help="Memory limit")
    up_parser.add_argument(
        "--env",
        action="append",
        default=[],
        type=validate_env_item,
        metavar="KEY=VALUE",
        help="Set environment variable in container. Can be specified multiple times.",
    )
    up_parser.add_argument("--shell", default="bash", help="Shell to start in kubectl exec")
    up_parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the pod after exiting instead of deleting it (only applies when newly created)",
    )
    up_parser.add_argument(
        "--forward",
        action="append",
        default=[],
        help="Port forward (format: local:remote). Can be specified multiple times.",
    )

    down_parser = subparsers.add_parser("down", help="Delete gpu-dev pod(s)")
    _add_name_argument(down_parser)
    down_parser.add_argument("--all", action="store_true", help="Delete all my gpu-dev pods")

    subparsers.add_parser("status", help="List my gpu-dev pods")

    return parser


def validate_env_item(item: str) -> str:
    if "=" not in item:
        raise argparse.ArgumentTypeError("expected KEY=VALUE")
    key, _ = item.split("=", 1)
    if not key:
        raise argparse.ArgumentTypeError("environment variable name is empty")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise argparse.ArgumentTypeError(
            f"invalid environment variable name: {key} (use [A-Za-z_][A-Za-z0-9_]*)"
        )
    return item


def parse_pull_policy(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    mapping = {
        "always": "Always",
        "if-not-present": "IfNotPresent",
        "ifnotpresent": "IfNotPresent",
        "never": "Never",
    }
    if normalized not in mapping:
        raise argparse.ArgumentTypeError(
            "invalid --pull value. use one of: always, if-not-present, never"
        )
    return mapping[normalized]


def parse_node_selector(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise SystemExit("[gpu-dev] invalid --node-selector value: expected KEY=VALUE")
    key, selector_value = value.split("=", 1)
    key = key.strip()
    selector_value = selector_value.strip()
    if not key:
        raise SystemExit("[gpu-dev] invalid --node-selector value: key is empty")
    if not selector_value:
        raise SystemExit("[gpu-dev] invalid --node-selector value: value is empty")
    return key, selector_value


def _normalize_config_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _extract_up_config(data) -> dict:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SystemExit("[gpu-dev] invalid config file: root must be a mapping")
    return data


def _normalize_env_values(value) -> list[str]:
    if value is None:
        return []

    if isinstance(value, dict):
        return [f"{k}={v}" for k, v in value.items()]

    if isinstance(value, list):
        items = []
        for item in value:
            if isinstance(item, str):
                items.append(validate_env_item(item))
            elif isinstance(item, dict):
                for k, v in item.items():
                    items.append(validate_env_item(f"{k}={v}"))
            else:
                raise SystemExit("[gpu-dev] invalid env config: list items must be string or mapping")
        return items

    raise SystemExit("[gpu-dev] invalid env config: must be mapping or list")


def _normalize_forward_values(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        values = [str(v) for v in value]
    elif isinstance(value, str):
        values = [value]
    else:
        raise SystemExit("[gpu-dev] invalid forward config: must be string or list")
    return validate_forwards(values)


def apply_up_file_config(args):
    if not args.file:
        return

    path = Path(args.file).expanduser()
    if not path.exists():
        raise SystemExit(f"[gpu-dev] config file not found: {path}")

    try:
        yaml = importlib.import_module("yaml")
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "[gpu-dev] PyYAML is required for --file support. Install dependency: PyYAML"
        ) from exc

    with path.open("r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f)

    config = _extract_up_config(raw_data)
    normalized = {_normalize_config_key(k): v for k, v in config.items()}

    defaults = {
        "ttl": DEFAULT_TTL,
        "gpu": DEFAULT_GPU,
        "image": DEFAULT_IMAGE,
        "pull": DEFAULT_PULL,
        "name": None,
        "pvc": DEFAULT_PVC,
        "mount_path": DEFAULT_MOUNT_PATH,
        "workdir": None,
        "runtime_class": DEFAULT_RUNTIME_CLASS,
        "node_selector": None,
        "node_label_key": DEFAULT_NODE_LABEL_KEY,
        "node_label_value": DEFAULT_NODE_LABEL_VALUE,
        "cpu_request": DEFAULT_CPU_REQUEST,
        "cpu_limit": DEFAULT_CPU_LIMIT,
        "memory_request": DEFAULT_MEMORY_REQUEST,
        "memory_limit": DEFAULT_MEMORY_LIMIT,
        "shell": "bash",
        "keep": False,
        "env": [],
        "forward": [],
    }

    aliases = {
        "mountpath": "mount_path",
        "mount_path": "mount_path",
        "runtimeclass": "runtime_class",
        "runtime_class": "runtime_class",
        "nodeselector": "node_selector",
        "node_selector": "node_selector",
        "node_label_key": "node_label_key",
        "node_label_value": "node_label_value",
        "cpu_request": "cpu_request",
        "cpu_limit": "cpu_limit",
        "memory_request": "memory_request",
        "memory_limit": "memory_limit",
    }

    for key, value in normalized.items():
        target = aliases.get(key, key)
        if target not in defaults:
            raise SystemExit(f"[gpu-dev] unsupported key in config: {key}")

        current = getattr(args, target)
        if current != defaults[target]:
            continue

        if target == "pull":
            setattr(args, target, parse_pull_policy(str(value)))
            continue
        if target == "node_selector":
            setattr(args, target, str(value))
            continue
        if target == "env":
            setattr(args, target, _normalize_env_values(value))
            continue
        if target == "forward":
            setattr(args, target, _normalize_forward_values(value))
            continue

        setattr(args, target, value)


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "up":
        apply_up_file_config(args)
        if args.node_selector:
            key, selector_value = parse_node_selector(args.node_selector)
            args.node_label_key = key
            args.node_label_value = selector_value
        else:
            args.node_label_key = DEFAULT_NODE_LABEL_KEY
            args.node_label_value = DEFAULT_NODE_LABEL_VALUE

    namespace = get_namespace_or_exit()

    owner = build_owner()

    env = os.environ.copy()
    env.pop("KUBECONFIG", None)

    if args.command == "status":
        list_pods(namespace, owner, env=env)
        return

    if args.command == "down":
        if args.all:
            delete_all_pods(namespace, owner, env=env)
        else:
            pod_name = build_pod_name(owner, args.name)
            delete_pod(namespace, pod_name, env=env)
        return

    if args.command != "up":
        raise SystemExit(f"unknown command: {args.command}")

    pod_name = build_pod_name(owner, args.name)

    forwards = validate_forwards(args.forward)

    pf_proc = None
    created = False

    try:
        created = ensure_pod(namespace, pod_name, owner, args, env=env)

        pf_proc = start_port_forward(namespace, pod_name, forwards, env=env)
        if pf_proc:
            time.sleep(1)

        run(
            ["kubectl", "-n", namespace, "exec", "-it", pod_name, "--", args.shell],
            env=env,
            check=False,
        )

    finally:
        stop_process(pf_proc, "port-forward")

        if created and not args.keep:
            print("[gpu-dev] deleting pod...")
            delete_pod(namespace, pod_name, env=env)


if __name__ == "__main__":
    main()