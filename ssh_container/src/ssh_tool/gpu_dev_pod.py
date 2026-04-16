import textwrap

from .gpu_dev_defaults import DEFAULT_CPU_LIMIT
from .gpu_dev_defaults import DEFAULT_CPU_REQUEST
from .gpu_dev_defaults import DEFAULT_GPU
from .gpu_dev_defaults import DEFAULT_IMAGE
from .gpu_dev_defaults import DEFAULT_MEMORY_LIMIT
from .gpu_dev_defaults import DEFAULT_MEMORY_REQUEST
from .gpu_dev_defaults import DEFAULT_MOUNT_PATH
from .gpu_dev_defaults import DEFAULT_NODE_LABEL_KEY
from .gpu_dev_defaults import DEFAULT_NODE_LABEL_VALUE
from .gpu_dev_defaults import DEFAULT_PULL
from .gpu_dev_defaults import DEFAULT_PVC
from .gpu_dev_defaults import DEFAULT_RUNTIME_CLASS
from .gpu_dev_defaults import DEFAULT_TTL
from .gpu_dev_identity import sanitize_k8s_name
from .gpu_dev_k8s import get_pod_phase
from .gpu_dev_k8s import kubectl_apply
from .gpu_dev_k8s import pod_exists
from .gpu_dev_k8s import run


def has_non_default_create_flags(args) -> bool:
    return any(
        [
            args.gpu != DEFAULT_GPU,
            args.image != DEFAULT_IMAGE,
            args.pull != DEFAULT_PULL,
            args.pvc != DEFAULT_PVC,
            args.mount_path != DEFAULT_MOUNT_PATH,
            args.runtime_class != DEFAULT_RUNTIME_CLASS,
            args.node_label_key != DEFAULT_NODE_LABEL_KEY,
            args.node_label_value != DEFAULT_NODE_LABEL_VALUE,
            args.cpu_request != DEFAULT_CPU_REQUEST,
            args.cpu_limit != DEFAULT_CPU_LIMIT,
            args.memory_request != DEFAULT_MEMORY_REQUEST,
            args.memory_limit != DEFAULT_MEMORY_LIMIT,
            args.ttl != DEFAULT_TTL,
            args.workdir is not None,
            bool(args.env),
        ]
    )


def _build_env_yaml(env_items: list[str]) -> str:
    if not env_items:
        return ""

    lines = ["          env:"]
    for item in env_items:
        key, value = item.split("=", 1)
        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f"            - name: {key}")
        lines.append(f'              value: "{escaped_value}"')
    return "\n" + "\n".join(lines)


def build_pod_manifest(args, pod_name: str, owner: str) -> str:
    logical_name = sanitize_k8s_name(args.name) if args.name else "default"
    working_dir = args.workdir if args.workdir else args.mount_path
    env_yaml = _build_env_yaml(args.env)
    return textwrap.dedent(
        f"""\
        apiVersion: v1
        kind: Pod
        metadata:
          name: {pod_name}
          labels:
            app: gpu-dev
            owner: {owner}
            logical-name: "{logical_name}"
          annotations:
            gpu-dev/gpu: "{args.gpu}"
            gpu-dev/cpu-request: "{args.cpu_request}"
            gpu-dev/cpu-limit: "{args.cpu_limit}"
            gpu-dev/memory-request: "{args.memory_request}"
            gpu-dev/memory-limit: "{args.memory_limit}"
            gpu-dev/pvc: "{args.pvc}"
            gpu-dev/mount-path: "{args.mount_path}"
        spec:
          restartPolicy: Never
          runtimeClassName: {args.runtime_class}
          nodeSelector:
            {args.node_label_key}: "{args.node_label_value}"
          containers:
            - name: dev
              image: {args.image}
              imagePullPolicy: {args.pull}
              workingDir: {working_dir}
              command: ["{args.shell}", "-c", "sleep {args.ttl}"]
              tty: true
              stdin: true{env_yaml}
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
        """
    )


def ensure_pod(namespace: str, pod_name: str, owner: str, args, env=None) -> bool:
    if pod_exists(namespace, pod_name, env=env):
        print(f"[gpu-dev] found existing pod: {pod_name}")

        phase = get_pod_phase(namespace, pod_name, env=env)
        if phase and phase != "Running":
            print(f"[gpu-dev] warning: pod phase is {phase}")

        if args.pull != DEFAULT_PULL:
            down_cmd = "gpu-dev down"
            up_cmd = f"gpu-dev up --pull {args.pull.lower()}"
            if args.name:
                down_cmd = f"{down_cmd} --name {args.name}"
                up_cmd = f"{up_cmd} --name {args.name}"
            print(
                "[gpu-dev] warning: --pull has no effect when reusing an existing pod. "
                f"Run `{down_cmd}` and then `{up_cmd}`."
            )

        if has_non_default_create_flags(args):
            print("[gpu-dev] existing pod found; create-time resource flags are ignored")
        return False

    print(f"[gpu-dev] pod not found: {pod_name}")
    print(f"[gpu-dev] creating new pod: {pod_name}")
    manifest = build_pod_manifest(args, pod_name, owner)
    kubectl_apply(namespace, manifest, env=env)

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
    return True
