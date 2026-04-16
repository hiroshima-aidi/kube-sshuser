#!/usr/bin/env python3

import json
from pathlib import Path

from kube_sshuser.common import kubectl_get_json, run


USER_LABEL_KEY = "provision-user.openai.local/user"
SSH_APP_LABEL = "app.kubernetes.io/name=ssh-user"


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


def kubectl_get_pod_name(namespace: str, username: str) -> str:
    result = run(
        [
            "kubectl",
            "-n",
            namespace,
            "get",
            "pods",
            "-l",
            f"{SSH_APP_LABEL},{USER_LABEL_KEY}={username}",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ]
    )
    pod_name = result.stdout.strip()
    if not pod_name:
        raise RuntimeError("failed to find ssh pod")
    return pod_name


def kubectl_get_node_name_of_pod(namespace: str, pod_name: str) -> str:
    result = run(
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
    node_name = result.stdout.strip()
    if not node_name:
        raise RuntimeError("failed to resolve nodeName of ssh pod")
    return node_name


def kubectl_get_node_ip(node_name: str, preferred_type: str) -> str:
    result = run(["kubectl", "get", "node", node_name, "-o", "json"])
    data = json.loads(result.stdout)
    addresses = data.get("status", {}).get("addresses", [])

    preferred = None
    internal = None
    external = None
    fallback = None

    for address in addresses:
        address_type = address.get("type")
        value = address.get("address")
        if not address_type or not value:
            continue
        if address_type == preferred_type and not preferred:
            preferred = value
        if address_type == "InternalIP" and not internal:
            internal = value
        if address_type == "ExternalIP" and not external:
            external = value
        if not fallback:
            fallback = value

    return preferred or external or internal or fallback or ""


def collect_observed_namespace_spec(namespace: str, pvc_name: str, deployment_name: str):
    quota = kubectl_get_json(
        ["kubectl", "-n", namespace, "get", "resourcequota", "quota", "-o", "json"]
    )
    pvc = kubectl_get_json(["kubectl", "-n", namespace, "get", "pvc", pvc_name, "-o", "json"])
    deployment = kubectl_get_json(
        ["kubectl", "-n", namespace, "get", "deployment", deployment_name, "-o", "json"]
    )

    deployment_spec = None
    if deployment:
        template_spec = deployment.get("spec", {}).get("template", {}).get("spec", {})
        containers = template_spec.get("containers", [])
        first_container = containers[0] if containers else {}
        ports = first_container.get("ports", [])
        first_port = ports[0] if ports else {}
        deployment_spec = {
            "image": first_container.get("image"),
            "host_port": first_port.get("hostPort"),
            "resources": first_container.get("resources"),
            "node_selector": template_spec.get("nodeSelector"),
        }

    return {
        "resource_quota_hard": quota.get("spec", {}).get("hard") if quota else None,
        "pvc_requested_storage": (
            pvc.get("spec", {}).get("resources", {}).get("requests", {}).get("storage")
            if pvc
            else None
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
