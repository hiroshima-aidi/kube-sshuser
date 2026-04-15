#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
import textwrap


def run(cmd, env=None, check=True):
    print(f"[cmd] {' '.join(cmd)}")
    return subprocess.run(cmd, env=env, check=check)


def kubectl_apply(namespace: str, manifest: str, env=None):
    proc = subprocess.Popen(
        ["kubectl", "-n", namespace, "apply", "--validate=false", "-f", "-"],
        stdin=subprocess.PIPE,
        text=True,
        env=env,
    )
    proc.communicate(manifest)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


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


def main():
    parser = argparse.ArgumentParser(
        description="Launch an interactive GPU dev pod using in-cluster ServiceAccount auth."
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
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the pod after exiting instead of deleting it",
    )

    args = parser.parse_args()

    namespace = os.environ.get("K8S_NAMESPACE")
    if not namespace:
        print("K8S_NAMESPACE is required", file=sys.stderr)
        sys.exit(1)

    invoking_user = (
        os.environ.get("USER")
        or os.environ.get("LOGNAME")
        or "user"
    )
    owner = sanitize_k8s_name(invoking_user)
    pod_name = args.name or f"gpu-dev-{owner}"

    env = os.environ.copy()
    env.pop("KUBECONFIG", None)

    manifest = textwrap.dedent(f"""\
        apiVersion: v1
        kind: Pod
        metadata:
          name: {pod_name}
          labels:
            app: gpu-dev
            owner: {owner}
        spec:
          restartPolicy: Never
          runtimeClassName: {args.runtime_class}
          nodeSelector:
            {args.node_label_key}: "{args.node_label_value}"
          containers:
            - name: dev
              image: {args.image}
              workingDir: {args.mount_path}
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

    created = False
    try:
        kubectl_apply(namespace, manifest, env=env)
        created = True

        run(
            [
                "kubectl",
                "-n",
                namespace,
                "wait",
                "--for=condition=Ready",
                f"pod/{pod_name}",
                "--timeout=180s",
            ],
            env=env,
        )

        run(
            ["kubectl", "-n", namespace, "exec", "-it", pod_name, "--", "bash"],
            env=env,
            check=False,
        )
    finally:
        if created and not args.keep:
            print("[gpu-dev] deleting pod...")
            run(
                [
                    "kubectl",
                    "-n",
                    namespace,
                    "delete",
                    "pod",
                    pod_name,
                    "--ignore-not-found",
                ],
                env=env,
                check=False,
            )


if __name__ == "__main__":
    main()