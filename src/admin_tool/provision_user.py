#!/usr/bin/env python3

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

from admin_tool.registry import (
    append_event,
    build_operation_id,
    extract_public_key_metadata,
    update_user_record,
    utcnow_iso,
)


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
    if len(value) > 63:
        value = value[:63].rstrip("-")
    if not value:
        raise ValueError("normalized name became empty after truncation")
    return value


def kubectl_apply(yaml_text: str):
    run(["kubectl", "apply", "-f", "-"], input_text=yaml_text, capture_output=False)


def kubectl_wait_deployment(namespace: str, name: str, timeout: str = "180s"):
    run(
        [
            "kubectl",
            "-n",
            namespace,
            "rollout",
            "status",
            f"deployment/{name}",
            f"--timeout={timeout}",
        ],
        capture_output=False,
    )


def kubectl_get_pod_name(namespace: str, label_selector: str) -> str:
    r = run(
        [
            "kubectl",
            "-n",
            namespace,
            "get",
            "pods",
            "-l",
            label_selector,
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ]
    )
    pod_name = r.stdout.strip()
    if not pod_name:
        raise RuntimeError("failed to find ssh pod")
    return pod_name


def kubectl_get_node_name_of_pod(namespace: str, pod_name: str) -> str:
    r = run(
        [
            "kubectl",
            "-n",
            namespace,
            "get",
            "pod",
            pod_name,
            "-o",
            "jsonpath={.spec.nodeName}",
        ]
    )
    node_name = r.stdout.strip()
    if not node_name:
        raise RuntimeError("failed to resolve nodeName of ssh pod")
    return node_name


def kubectl_get_node_ip(node_name: str, preferred_type: str) -> str:
    r = run(["kubectl", "get", "node", node_name, "-o", "json"])
    data = json.loads(r.stdout)
    addresses = data.get("status", {}).get("addresses", [])

    preferred = None
    internal = None
    external = None
    fallback = None

    for addr in addresses:
        typ = addr.get("type")
        val = addr.get("address")
        if not typ or not val:
            continue
        if typ == preferred_type and not preferred:
            preferred = val
        if typ == "InternalIP" and not internal:
            internal = val
        if typ == "ExternalIP" and not external:
            external = val
        if not fallback:
            fallback = val

    return preferred or external or internal or fallback or ""


def kubectl_get_json(cmd):
    r = run(cmd, check=False)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def collect_observed_namespace_spec(namespace: str, pvc_name: str, deployment_name: str):
    quota = kubectl_get_json(["kubectl", "-n", namespace, "get", "resourcequota", "quota", "-o", "json"])
    pvc = kubectl_get_json(["kubectl", "-n", namespace, "get", "pvc", pvc_name, "-o", "json"])
    deployment = kubectl_get_json(["kubectl", "-n", namespace, "get", "deployment", deployment_name, "-o", "json"])

    deployment_spec = None
    if deployment:
        tpl_spec = deployment.get("spec", {}).get("template", {}).get("spec", {})
        containers = tpl_spec.get("containers", [])
        first_container = containers[0] if containers else {}
        ports = first_container.get("ports", [])
        first_port = ports[0] if ports else {}
        deployment_spec = {
            "image": first_container.get("image"),
            "host_port": first_port.get("hostPort"),
            "resources": first_container.get("resources"),
            "node_selector": tpl_spec.get("nodeSelector"),
        }

    return {
        "resource_quota_hard": quota.get("spec", {}).get("hard") if quota else None,
        "pvc_requested_storage": (
            pvc.get("spec", {}).get("resources", {}).get("requests", {}).get("storage") if pvc else None
        ),
        "deployment": deployment_spec,
    }


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


def build_manifest(args, public_key: str) -> str:
    quota_block = ""
    if args.gpu_quota >= 0:
        quota_block = f"""\
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: quota
  namespace: {args.namespace}
  labels:
    app.kubernetes.io/managed-by: provision-user
    provision-user.openai.local/user: {args.username}
spec:
  hard:
    requests.cpu: "{args.cpu_quota}"
    limits.cpu: "{args.cpu_quota}"
    requests.memory: "{args.memory_quota}"
    limits.memory: "{args.memory_quota}"
    requests.storage: "{args.storage}"
    persistentvolumeclaims: "5"
    requests.nvidia.com/gpu: "{args.gpu_quota}"
    limits.nvidia.com/gpu: "{args.gpu_quota}"
"""

    return f"""\
apiVersion: v1
kind: Namespace
metadata:
  name: {args.namespace}
  labels:
    app.kubernetes.io/managed-by: provision-user
    provision-user.openai.local/user: {args.username}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {args.pvc_name}
  namespace: {args.namespace}
  labels:
    app.kubernetes.io/managed-by: provision-user
    provision-user.openai.local/user: {args.username}
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: {args.storage}
{quota_block}---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {args.service_account_name}
  namespace: {args.namespace}
  labels:
    app.kubernetes.io/managed-by: provision-user
    provision-user.openai.local/user: {args.username}
automountServiceAccountToken: true
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {args.role_name}
  namespace: {args.namespace}
  labels:
    app.kubernetes.io/managed-by: provision-user
    provision-user.openai.local/user: {args.username}
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch", "create", "delete"]
  - apiGroups: [""]
    resources: ["pods/exec"]
    verbs: ["create"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get", "list"]
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {args.role_binding_name}
  namespace: {args.namespace}
  labels:
    app.kubernetes.io/managed-by: provision-user
    provision-user.openai.local/user: {args.username}
subjects:
  - kind: ServiceAccount
    name: {args.service_account_name}
    namespace: {args.namespace}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {args.role_name}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {args.deployment_name}
  namespace: {args.namespace}
  labels:
    app.kubernetes.io/name: ssh-user
    app.kubernetes.io/managed-by: provision-user
    provision-user.openai.local/user: {args.username}
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: ssh-user
      provision-user.openai.local/user: {args.username}
  strategy:
    type: Recreate
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ssh-user
        app.kubernetes.io/managed-by: provision-user
        provision-user.openai.local/user: {args.username}
    spec:
      serviceAccountName: {args.service_account_name}
      automountServiceAccountToken: true
      nodeSelector:
        {args.login_node_label_key}: "{args.login_node_label_value}"
      terminationGracePeriodSeconds: 30
      containers:
        - name: ssh
          image: {args.image}
          imagePullPolicy: IfNotPresent
          ports:
            - name: ssh
              containerPort: 22
              hostPort: {args.port}
              protocol: TCP
          env:
            - name: SSH_USER
              value: "{args.username}"
            - name: SSH_UID
              value: "{args.ssh_uid}"
            - name: SSH_GROUP
              value: "{args.username}"
            - name: SSH_GID
              value: "{args.ssh_gid}"
            - name: SSH_PUBLIC_KEY
              value: "{public_key}"
            - name: K8S_NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
          resources:
            requests:
              cpu: "{args.ssh_cpu_request}"
              memory: "{args.ssh_memory_request}"
            limits:
              cpu: "{args.ssh_cpu_limit}"
              memory: "{args.ssh_memory_limit}"
          securityContext:
            allowPrivilegeEscalation: false
          readinessProbe:
            tcpSocket:
              port: 22
            initialDelaySeconds: 3
            periodSeconds: 5
          livenessProbe:
            tcpSocket:
              port: 22
            initialDelaySeconds: 10
            periodSeconds: 10
"""


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Provision one namespace + PVC + quota + SA/RBAC + SSH deployment."
    )
    p.add_argument("--user", required=True, help="logical username, e.g. taro")

    key_group = p.add_mutually_exclusive_group(required=True)
    key_group.add_argument(
        "--public-key-file",
        help="path to user's SSH public key file",
    )
    key_group.add_argument(
        "--public-key-string",
        help="SSH public key string",
    )

    p.add_argument("--image", required=True, help="SSH pod image")
    p.add_argument("--port", type=int, required=True, help="hostPort to expose SSH on login node")

    p.add_argument("--storage", default="100Gi", help="workspace PVC size")
    p.add_argument("--pvc-name", default="workspace", help="workspace PVC name")
    p.add_argument("--gpu-quota", type=int, default=1, help="GPU quota for the namespace")
    p.add_argument("--cpu-quota", default="16", help="CPU quota")
    p.add_argument("--memory-quota", default="64Gi", help="memory quota")

    p.add_argument("--ssh-uid", type=int, default=2000, help="UID inside SSH container")
    p.add_argument("--ssh-gid", type=int, default=2000, help="GID inside SSH container")

    p.add_argument("--ssh-cpu-request", default="100m", help="ssh pod cpu request")
    p.add_argument("--ssh-cpu-limit", default="1", help="ssh pod cpu limit")
    p.add_argument("--ssh-memory-request", default="128Mi", help="ssh pod memory request")
    p.add_argument("--ssh-memory-limit", default="1Gi", help="ssh pod memory limit")

    p.add_argument("--namespace", default=None, help="override namespace")
    p.add_argument("--out-dir", default="./out", help="output directory")

    p.add_argument("--login-node-label-key", default="role", help="node label key for login server")
    p.add_argument("--login-node-label-value", default="login-server", help="node label value for login server")

    p.add_argument(
        "--node-address-type",
        default="ExternalIP",
        choices=["ExternalIP", "InternalIP"],
        help="preferred node address type to report for SSH endpoint",
    )

    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    username_norm = normalize_name(args.user)
    args.username = username_norm
    args.namespace = args.namespace or normalize_name(f"ns-{username_norm}")

    args.service_account_name = "ssh-user"
    args.role_name = "ssh-user-role"
    args.role_binding_name = "ssh-user-binding"
    args.deployment_name = normalize_name(f"ssh-{username_norm}")

    public_key = resolve_public_key(args)

    out_dir = (Path(args.out_dir) / username_norm).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = (out_dir / f"provision-{username_norm}.yaml").resolve()

    manifest = build_manifest(args, public_key)
    manifest_path.write_text(manifest, encoding="utf-8")

    print("[1/3] applying namespace / pvc / quota / sa / rbac / deployment...", file=sys.stderr)
    kubectl_apply(manifest)

    print("[2/3] waiting for ssh deployment rollout...", file=sys.stderr)
    kubectl_wait_deployment(args.namespace, args.deployment_name)

    print("[3/3] collecting endpoint info...", file=sys.stderr)
    pod_name = kubectl_get_pod_name(
        args.namespace,
        f"app.kubernetes.io/name=ssh-user,provision-user.openai.local/user={args.username}",
    )
    node_name = kubectl_get_node_name_of_pod(args.namespace, pod_name)
    node_ip = kubectl_get_node_ip(node_name, args.node_address_type)
    operation_id = build_operation_id("create")
    event_time = utcnow_iso()

    requested_spec = {
        "resource_quota": {
            "cpu": args.cpu_quota,
            "memory": args.memory_quota,
            "gpu": args.gpu_quota,
            "storage": args.storage,
            "persistentvolumeclaims": "5",
        },
        "pvc": {
            "name": args.pvc_name,
            "storage": args.storage,
        },
        "ssh_deployment": {
            "image": args.image,
            "host_port": args.port,
            "node_selector": {
                args.login_node_label_key: args.login_node_label_value,
            },
            "resources": {
                "requests": {
                    "cpu": args.ssh_cpu_request,
                    "memory": args.ssh_memory_request,
                },
                "limits": {
                    "cpu": args.ssh_cpu_limit,
                    "memory": args.ssh_memory_limit,
                },
            },
        },
    }
    observed_spec = collect_observed_namespace_spec(args.namespace, args.pvc_name, args.deployment_name)

    record_path, _ = update_user_record(
        args.out_dir,
        args.username,
        {
            "status": "active",
            "last_operation_id": operation_id,
            "ssh": {
                "port": args.port,
                "endpoint": f"{node_ip}:{args.port}" if node_ip else None,
                "host_ip": node_ip,
                "node": node_name,
                "pod": pod_name,
            },
            "ssh_key": extract_public_key_metadata(public_key),
            "namespace": {
                "name": args.namespace,
                "spec": {
                    "requested": requested_spec,
                    "observed": observed_spec,
                },
            },
            "paths": {
                "output_dir": str(out_dir),
                "manifest_path": str(manifest_path),
            },
        },
    )

    events_path = append_event(
      args.out_dir,
      {
        "event_id": operation_id,
        "time": event_time,
        "action": "create",
        "user": args.username,
        "status": "active",
        "namespace": args.namespace,
        "ssh_port": args.port,
        "ssh_endpoint": f"{node_ip}:{args.port}" if node_ip else None,
        "manifest_path": str(manifest_path),
      },
    )

    summary = {
        "user": args.username,
        "namespace": args.namespace,
        "pvc": args.pvc_name,
        "service_account": args.service_account_name,
        "role": args.role_name,
        "role_binding": args.role_binding_name,
        "deployment": args.deployment_name,
        "ssh_pod": pod_name,
        "ssh_node": node_name,
        "ssh_host_ip": node_ip,
        "ssh_port": args.port,
        "ssh_endpoint": f"{node_ip}:{args.port}" if node_ip else None,
        "manifest_path": str(manifest_path),
        "registry_record_path": str(record_path),
        "registry_events_path": str(events_path),
        "registry_base_dir": str((Path(args.out_dir).expanduser().resolve() / "_registry")),
        "notes": [
            "SSH pod uses in-cluster ServiceAccount auth; no admin kubeconfig is copied into the pod.",
            "workspace PVC is created but not mounted into the SSH pod to avoid RWO multi-attach issues before RWX/NFS is introduced.",
            "gpu-dev is intended to run as the normal SSH user, not via sudo.",
            "SSH is exposed via hostPort on a login-server-labeled node, so the endpoint is that node's IP and the specified port.",
        ],
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()