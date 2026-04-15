#!/usr/bin/env python3

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml


def run(cmd, input_text=None, check=True, capture_output=True):
    if isinstance(cmd, str):
        shell = True
        printable = cmd
    else:
        shell = False
        printable = " ".join(shlex.quote(str(x)) for x in cmd)

    print(f"[cmd] {printable}", file=sys.stderr)
    return subprocess.run(
        cmd,
        input=input_text,
        text=True,
        check=check,
        capture_output=capture_output,
        shell=shell,
    )


def normalize_name(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    value = value.strip("-")
    if not value:
        raise ValueError("normalized name became empty")
    return value


def kubectl_jsonpath(expr: str) -> str:
    r = run(["kubectl", "config", "view", "--raw", "--minify", "-o", f"jsonpath={expr}"])
    return r.stdout.strip()


def get_cluster_info():
    server = kubectl_jsonpath("{.clusters[0].cluster.server}")
    ca_cert_b64 = kubectl_jsonpath("{.clusters[0].cluster.certificate-authority-data}")
    if not server or not ca_cert_b64:
        raise RuntimeError("failed to read cluster server or CA cert from current kubeconfig")
    return server, ca_cert_b64


def kubectl_apply(yaml_text: str):
    run(["kubectl", "apply", "-f", "-"], input_text=yaml_text, capture_output=False)


def build_namespace_yaml(
    namespace: str,
    storage: str,
    gpu_quota: int,
    cpu_quota: str,
    memory_quota: str,
    pvc_name: str,
):
    quota_block = f"""\
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: quota
  namespace: {namespace}
spec:
  hard:
    requests.cpu: "{cpu_quota}"
    limits.cpu: "{cpu_quota}"
    requests.memory: "{memory_quota}"
    limits.memory: "{memory_quota}"
    requests.storage: "{storage}"
    persistentvolumeclaims: "5"
    requests.nvidia.com/gpu: "{gpu_quota}"
    limits.nvidia.com/gpu: "{gpu_quota}"
""" if gpu_quota >= 0 else ""

    return f"""\
apiVersion: v1
kind: Namespace
metadata:
  name: {namespace}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {pvc_name}
  namespace: {namespace}
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: {storage}
{quota_block}"""


def write_admin_kubeconfig_copy(path: Path, server_override: str | None = None):
    r = run(["kubectl", "config", "view", "--raw", "--minify"])
    content = r.stdout
    if not content.strip():
        raise RuntimeError("failed to get raw kubeconfig from current context")

    config = yaml.safe_load(content)

    if server_override:
        try:
            config["clusters"][0]["cluster"]["server"] = server_override
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("failed to override kubeconfig server") from exc

    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    os.chmod(path, 0o600)


def docker_rm_if_exists(name: str):
    run(["docker", "rm", "-f", name], check=False)


def resolve_public_key(args) -> str:
    if args.public_key_file:
        public_key_path = Path(args.public_key_file).expanduser().resolve()
        public_key = public_key_path.read_text(encoding="utf-8").strip()
    else:
        public_key = args.public_key_string.strip()

    if not public_key:
        raise RuntimeError("public key is empty")

    if not (
        public_key.startswith("ssh-")
        or public_key.startswith("ecdsa-")
        or public_key.startswith("sk-")
    ):
        raise RuntimeError("public key does not look like a valid SSH public key")

    return public_key


def docker_run(args):
    public_key = resolve_public_key(args)
    admin_kubeconfig_host_path = str(Path(args.admin_kubeconfig_copy).resolve())

    envs = [
        "SSH_USER", args.username,
        "SSH_UID", str(args.ssh_uid),
        "SSH_GROUP", args.username,
        "SSH_GID", str(args.ssh_gid),
        "SSH_PUBLIC_KEY", public_key,
        "K8S_NAMESPACE", args.namespace,
        "K8S_SERVER", args.k8s_server,
        "K8S_CA_CERT_B64", args.k8s_ca_cert_b64,
        "K8S_ADMIN_KUBECONFIG", "/etc/kube/admin.kubeconfig",
    ]

    cmd = [
        "docker", "run", "-d",
        "--name", args.container_name,
        "-p", f"{args.port}:22",
        "-v", f"{admin_kubeconfig_host_path}:/etc/kube/admin.kubeconfig:ro",
    ]

    for i in range(0, len(envs), 2):
        cmd += ["-e", f"{envs[i]}={envs[i+1]}"]

    cmd.append(args.image)
    run(cmd, capture_output=False)


def parse_args():
    p = argparse.ArgumentParser(
        description="Provision one SSH container + namespace + PVC + quota."
    )
    p.add_argument("--user", required=True, help="logical username, e.g. taro")

    key_group = p.add_mutually_exclusive_group(required=True)
    key_group.add_argument(
        "--public-key-file",
        help="path to user's SSH public key file"
    )
    key_group.add_argument(
        "--public-key-string",
        help="SSH public key string"
    )

    p.add_argument("--image", required=True, help="SSH container image")
    p.add_argument("--port", type=int, required=True, help="host SSH port to expose")
    p.add_argument(
        "--api-server",
        default=None,
        help="override Kubernetes API server URL, e.g. https://133.41.116.80:6443",
    )
    p.add_argument("--storage", default="100Gi", help="workspace PVC size")
    p.add_argument("--pvc-name", default="workspace", help="workspace PVC name")
    p.add_argument("--gpu-quota", type=int, default=1, help="GPU quota for the namespace")
    p.add_argument("--cpu-quota", default="16", help="CPU quota")
    p.add_argument("--memory-quota", default="64Gi", help="memory quota")
    p.add_argument("--ssh-uid", type=int, default=2000, help="UID inside SSH container")
    p.add_argument("--ssh-gid", type=int, default=2000, help="GID inside SSH container")
    p.add_argument("--out-dir", default="./out", help="output directory")
    p.add_argument("--container-name", default=None, help="docker container name")
    p.add_argument("--namespace", default=None, help="override namespace")
    return p.parse_args()


def main():
    args = parse_args()

    username_norm = normalize_name(args.user)
    args.username = username_norm
    args.namespace = args.namespace or normalize_name(f"ns-{username_norm}")
    args.container_name = args.container_name or normalize_name(f"ssh-{username_norm}")

    out_dir = (Path(args.out_dir) / username_norm).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    namespace_yaml_path = (out_dir / f"namespace-{username_norm}.yaml").resolve()
    admin_kubeconfig_copy_path = (out_dir / f"admin-{username_norm}.kubeconfig").resolve()

    detected_k8s_server, args.k8s_ca_cert_b64 = get_cluster_info()
    args.k8s_server = args.api_server or detected_k8s_server

    namespace_yaml = build_namespace_yaml(
        namespace=args.namespace,
        storage=args.storage,
        gpu_quota=args.gpu_quota,
        cpu_quota=args.cpu_quota,
        memory_quota=args.memory_quota,
        pvc_name=args.pvc_name,
    )
    namespace_yaml_path.write_text(namespace_yaml, encoding="utf-8")

    print("[1/4] applying namespace / pvc / quota...", file=sys.stderr)
    kubectl_apply(namespace_yaml)

    print("[2/4] writing admin kubeconfig copy...", file=sys.stderr)
    write_admin_kubeconfig_copy(admin_kubeconfig_copy_path, server_override=args.k8s_server)
    args.admin_kubeconfig_copy = str(admin_kubeconfig_copy_path)

    print("[3/4] starting ssh container...", file=sys.stderr)
    docker_rm_if_exists(args.container_name)
    docker_run(args)

    summary = {
        "user": args.username,
        "namespace": args.namespace,
        "pvc": args.pvc_name,
        "docker_container": args.container_name,
        "ssh_port": args.port,
        "api_server": args.k8s_server,
        "namespace_yaml": str(namespace_yaml_path),
        "admin_kubeconfig_copy": str(admin_kubeconfig_copy_path),
    }

    print("[4/4] done", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()