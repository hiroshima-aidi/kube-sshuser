import subprocess
from typing import Optional


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


def pod_exists(namespace: str, pod_name: str, env=None) -> bool:
    result = subprocess.run(
        ["kubectl", "-n", namespace, "get", "pod", pod_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    return result.returncode == 0


def get_pod_phase(namespace: str, pod_name: str, env=None) -> str:
    result = subprocess.run(
        [
            "kubectl",
            "-n",
            namespace,
            "get",
            "pod",
            pod_name,
            "-o",
            "jsonpath={.status.phase}",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def delete_pod(namespace: str, pod_name: str, env=None):
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


def delete_all_pods(namespace: str, owner: str, env=None):
    run(
        [
            "kubectl",
            "-n",
            namespace,
            "delete",
            "pod",
            "-l",
            f"app=gpu-dev,owner={owner}",
            "--ignore-not-found",
        ],
        env=env,
        check=False,
    )


def validate_forwards(forwards: list[str]) -> list[str]:
    validated = []
    for item in forwards:
        if ":" not in item:
            raise SystemExit(f"Invalid --forward value: {item} (expected local:remote)")
        local, remote = item.split(":", 1)
        if not local.isdigit() or not remote.isdigit():
            raise SystemExit(
                f"Invalid --forward value: {item} (local and remote must be integers)"
            )
        validated.append(f"{int(local)}:{int(remote)}")
    return validated


def can_create_pod_portforward(namespace: str, env=None) -> Optional[bool]:
    result = subprocess.run(
        [
            "kubectl",
            "-n",
            namespace,
            "auth",
            "can-i",
            "create",
            "pods/portforward",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    if result.returncode != 0:
        return None

    answer = result.stdout.strip().lower()
    if answer in {"yes", "true"}:
        return True
    if answer in {"no", "false"}:
        return False
    return None


def start_port_forward(namespace: str, pod_name: str, forwards: list[str], env=None):
    if not forwards:
        return None

    can_forward = can_create_pod_portforward(namespace, env=env)
    if can_forward is False:
        print(
            "[gpu-dev] warning: skip port-forward because this ServiceAccount "
            "cannot create pods/portforward"
        )
        print(
            "[gpu-dev] hint: add RBAC permission: apiGroups=[''], "
            "resources=['pods/portforward'], verbs=['create']"
        )
        return None

    cmd = [
        "kubectl",
        "-n",
        namespace,
        "port-forward",
        f"pod/{pod_name}",
    ] + forwards

    print(f"[port-forward] {' '.join(cmd)}")
    return subprocess.Popen(cmd, env=env)


def stop_process(proc: Optional[subprocess.Popen], name: str):
    if not proc:
        return
    print(f"[gpu-dev] stopping {name}...")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
