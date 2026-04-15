#!/usr/bin/env python3

import argparse
import os
import time

from .gpu_dev_core import DEFAULT_CPU_LIMIT
from .gpu_dev_core import DEFAULT_CPU_REQUEST
from .gpu_dev_core import DEFAULT_GPU
from .gpu_dev_core import DEFAULT_IMAGE
from .gpu_dev_core import DEFAULT_MEMORY_LIMIT
from .gpu_dev_core import DEFAULT_MEMORY_REQUEST
from .gpu_dev_core import DEFAULT_MOUNT_PATH
from .gpu_dev_core import DEFAULT_NODE_LABEL_KEY
from .gpu_dev_core import DEFAULT_NODE_LABEL_VALUE
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or attach to an interactive GPU dev pod using in-cluster ServiceAccount auth."
    )
    parser.add_argument("--ttl", type=int, default=DEFAULT_TTL, help="Pod lifetime in seconds")
    parser.add_argument("--gpu", type=int, default=DEFAULT_GPU, help="Number of GPUs")
    parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE,
        help="Container image",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Logical pod name. Example: --name test1 -> gpu-dev-<owner>-test1",
    )
    parser.add_argument("--pvc", default=DEFAULT_PVC, help="PVC name to mount")
    parser.add_argument("--mount-path", default=DEFAULT_MOUNT_PATH, help="PVC mount path")
    parser.add_argument("--runtime-class", default=DEFAULT_RUNTIME_CLASS, help="RuntimeClass name")
    parser.add_argument("--node-label-key", default=DEFAULT_NODE_LABEL_KEY, help="Node selector key")
    parser.add_argument(
        "--node-label-value", default=DEFAULT_NODE_LABEL_VALUE, help="Node selector value"
    )
    parser.add_argument("--cpu-request", default=DEFAULT_CPU_REQUEST, help="CPU request")
    parser.add_argument("--cpu-limit", default=DEFAULT_CPU_LIMIT, help="CPU limit")
    parser.add_argument("--memory-request", default=DEFAULT_MEMORY_REQUEST, help="Memory request")
    parser.add_argument("--memory-limit", default=DEFAULT_MEMORY_LIMIT, help="Memory limit")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the pod after exiting instead of deleting it (only applies when newly created)",
    )
    parser.add_argument(
        "--forward",
        action="append",
        default=[],
        help="Port forward (format: local:remote). Can be specified multiple times.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List my gpu-dev pods and exit",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete the target gpu-dev pod and exit",
    )
    parser.add_argument(
        "--delete-all",
        action="store_true",
        help="Delete all my gpu-dev pods and exit",
    )
    return parser


def handle_immediate_actions(args, namespace: str, owner: str, pod_name: str, env=None) -> bool:
    if args.list:
        list_pods(namespace, owner, env=env)
        return True

    if args.delete_all:
        delete_all_pods(namespace, owner, env=env)
        return True

    if args.delete:
        delete_pod(namespace, pod_name, env=env)
        return True

    return False


def main():
    parser = build_parser()
    args = parser.parse_args()

    namespace = get_namespace_or_exit()

    owner = build_owner()
    pod_name = build_pod_name(owner, args.name)

    env = os.environ.copy()
    env.pop("KUBECONFIG", None)

    if handle_immediate_actions(args, namespace, owner, pod_name, env=env):
        return

    forwards = validate_forwards(args.forward)

    pf_proc = None
    created = False

    try:
        created = ensure_pod(namespace, pod_name, owner, args, env=env)

        pf_proc = start_port_forward(namespace, pod_name, forwards, env=env)
        if pf_proc:
            time.sleep(1)

        run(
            ["kubectl", "-n", namespace, "exec", "-it", pod_name, "--", "bash"],
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