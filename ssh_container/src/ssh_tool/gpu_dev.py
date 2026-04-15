#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
import textwrap


def run(cmd, env=None, check=True):
    print(f"[cmd] {' '.join(cmd)}")
    return subprocess.run(cmd, env=env, check=check)


def kubectl_apply(namespace: str, manifest: str, kubeconfig: str):
    env = os.environ.copy()
    env["KUBECONFIG"] = kubeconfig

    proc = subprocess.Popen(
        ["kubectl", "-n", namespace, "apply", "--validate=false", "-f", "-"],
        stdin=subprocess.PIPE,
        text=True,
        env=env,
    )
    proc.communicate(manifest)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def main():
    parser = argparse.ArgumentParser(
        description="Launch an interactive GPU dev pod using admin kubeconfig."
    )
    parser.add_argument("--ttl", type=int, default=3600, help="Pod lifetime in seconds")
    parser.add_argument("--gpu", type=int, default=1, help="Number of GPUs")
    parser.add_argument(
        "--image",
        default="nvidia/cuda:12.2.0-runtime-ubuntu22.04",
        help="Container image",
    )
    parser.add_argument("--name", default=None, help="Pod name")
    parser.add_argument("--pvc", default="workspace", help="PVC name to mount")
    parser.add_argument("--mount-path", default="/workspace", help="PVC mount path")
    parser.add_argument("--runtime-class", default="nvidia", help="RuntimeClass name")
    parser.add_argument("--node-label-key", default="gpu", help="Node selector key")
    parser.add_argument("--node-label-value", default="true", help="Node selector value")

    parser.add_argument("--cpu-request", default="2", help="CPU request")
    parser.add_argument("--cpu-limit", default="4", help="CPU limit")
    parser.add_argument("--memory-request", default="8Gi", help="Memory request")
    parser.add_argument("--memory-limit", default="16Gi", help="Memory limit")

    args = parser.parse_args()

    namespace = os.environ.get("K8S_NAMESPACE")
    if not namespace:
        print("K8S_NAMESPACE is required", file=sys.stderr)
        sys.exit(1)

    admin_kubeconfig = os.environ.get("K8S_ADMIN_KUBECONFIG")
    if not admin_kubeconfig:
        print("K8S_ADMIN_KUBECONFIG is required", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(admin_kubeconfig):
        print(f"K8S_ADMIN_KUBECONFIG not found: {admin_kubeconfig}", file=sys.stderr)
        sys.exit(1)

    invoking_user = (
        os.environ.get("SUDO_USER")
        or os.environ.get("USER")
        or "user"
    )

    pod_name = args.name or f"gpu-dev-{invoking_user}"

    env = os.environ.copy()
    env["KUBECONFIG"] = admin_kubeconfig

    manifest = textwrap.dedent(f"""\
        apiVersion: v1
        kind: Pod
        metadata:
          name: {pod_name}
          labels:
            app: gpu-dev
            owner: {invoking_user}
        spec:
          restartPolicy: Never
          runtimeClassName: {args.runtime_class}
          nodeSelector:
            {args.node_label_key}: "{args.node_label_value}"
          containers:
          - name: dev
            image: {args.image}
            command: ["/bin/bash", "-lc", "sleep {args.ttl}"]
            tty: true
            stdin: true
            resources:
              requests:
                cpu: "{args.cpu_request}"
                memory: "{args.memory_request}"
              limits:
                cpu: "{args.cpu_limit}"
                memory: "{args.memory_limit}"
                nvidia.com/gpu: {args.gpu}
            volumeMounts:
            - name: workspace
              mountPath: {args.mount_path}
          volumes:
          - name: workspace
            persistentVolumeClaim:
              claimName: {args.pvc}
    """)

    try:
        kubectl_apply(namespace, manifest, admin_kubeconfig)
        run(
            ["kubectl", "-n", namespace, "wait", "--for=condition=Ready", f"pod/{pod_name}", "--timeout=180s"],
            env=env,
        )
        run(
            ["kubectl", "-n", namespace, "exec", "-it", pod_name, "--", "bash"],
            env=env,
            check=False,
        )
    finally:
        print("[gpu-dev] deleting pod...")
        run(
            ["kubectl", "-n", namespace, "delete", "pod", pod_name, "--ignore-not-found"],
            env=env,
            check=False,
        )


if __name__ == "__main__":
    main()