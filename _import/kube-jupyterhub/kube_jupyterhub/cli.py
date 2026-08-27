#!/usr/bin/env python3
import argparse
import shlex
import subprocess
import sys
from typing import Optional


DEFAULT_NAMESPACE = "jupyterhub"
DEFAULT_RELEASE = "jupyterhub"
DEFAULT_VALUES = "config.yaml"

# Each tool spells "which cluster" differently. Keeping the mapping in one table
# means adding a new tool (kustomize, flux, ...) is a one-line change instead of
# another special case at the call site.
CONTEXT_FLAGS = {
    "kubectl": "--context",
    "helm": "--kube-context",
}

_kube_context: Optional[str] = None
_dry_run: bool = False


def set_kube_context(context: Optional[str]) -> None:
    global _kube_context
    _kube_context = context


def set_dry_run(dry_run: bool) -> None:
    global _dry_run
    _dry_run = dry_run


def _with_context(cmd: list[str]) -> list[str]:
    parts = [str(part) for part in cmd]
    if not _kube_context or not parts:
        return parts
    flag = CONTEXT_FLAGS.get(parts[0])
    if flag is None:
        return parts
    return [parts[0], flag, _kube_context, *parts[1:]]


def run(
    cmd: list[str],
    check: bool = True,
    input_text: Optional[str] = None,
    note: Optional[str] = None,
) -> int:
    """Run one external command, echoing exactly what is executed.

    `note` annotates the echoed argv when the command reads a manifest from stdin
    and the argv alone would not say what is being applied.
    """
    argv = _with_context(cmd)
    printable = " ".join(shlex.quote(part) for part in argv)
    if note:
        printable += f"  # {note}"

    # [cmd]/[dry-run] go to stderr, progress goes to stdout; flush so the two
    # streams stay in order when the output is captured to a file.
    sys.stdout.flush()

    if _dry_run:
        print(f"[dry-run] {printable}", file=sys.stderr)
        return 0

    print(f"[cmd] {printable}", file=sys.stderr)
    proc = subprocess.run(argv, input=input_text.encode() if input_text else None)
    if check and proc.returncode != 0:
        sys.exit(proc.returncode)
    return proc.returncode


def confirm_typed_or_exit(expected: str, prompt: str, assume_yes: bool) -> None:
    """Require the operator to type an exact string to proceed.

    Exits non-zero when the input does not match, so a declined confirmation is
    distinguishable from a completed run in scripts.
    """
    if assume_yes:
        return
    reply = input(f"{prompt}\nType '{expected}' to confirm: ").strip()
    if reply != expected:
        print("aborted (input did not match)", file=sys.stderr)
        sys.exit(1)


def prepull_images(namespace: str, images: list[str]) -> None:
    for image in images:
        print(f"[INFO] Pre-pulling image on all nodes: {image}")
    ds_name = "kube-jupyterhub-image-puller"
    containers = "\n".join(
        f'      - name: puller-{i}\n'
        f'        image: "{image}"\n'
        f'        command: ["sh", "-c", "sleep 3600"]'
        for i, image in enumerate(images)
    )
    manifest = f"""\
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: {ds_name}
  namespace: {namespace}
spec:
  selector:
    matchLabels:
      app: {ds_name}
  template:
    metadata:
      labels:
        app: {ds_name}
    spec:
      tolerations:
      - operator: Exists
      containers:
{containers}
"""
    run(
        ["kubectl", "apply", "-f", "-"],
        input_text=manifest,
        note=f"DaemonSet/{ds_name}",
    )
    run(["kubectl", "rollout", "status", f"daemonset/{ds_name}", "-n", namespace])
    run(["kubectl", "delete", "daemonset", ds_name, "-n", namespace, "--ignore-not-found"])
    print("[INFO] Pre-pull complete.")


def apply_config(args: argparse.Namespace) -> None:
    print("[INFO] Applying JupyterHub config...")

    if args.pull:
        prepull_images(args.namespace, args.pull)

    run([
        "helm", "upgrade", "--install",
        args.release, "jupyterhub/jupyterhub",
        "--namespace", args.namespace,
        "--create-namespace",
        "--values", args.values,
    ])

    if args.wait:
        print("[INFO] Waiting for rollout...")
        run([
            "kubectl", "rollout", "status",
            "deploy/hub",
            "-n", args.namespace,
        ])

    print("[INFO] Done.")


def refresh_user(args: argparse.Namespace) -> None:
    pvc_name = f"claim-{args.username}"

    if args.full:
        print(f"[WARN] This will DELETE ALL DATA for user: {args.username}")
        print(f"[WARN] PVC to be deleted: {pvc_name} (namespace: {args.namespace})")
        confirm_typed_or_exit(
            pvc_name,
            f"This permanently destroys the contents of PVC {pvc_name}.",
            args.yes,
        )

    print(f"[INFO] Deleting pod for user: {args.username}")
    run([
        "kubectl", "delete", "pod",
        "-n", args.namespace,
        f"jupyter-{args.username}",
        "--ignore-not-found",
    ], check=False)

    if args.full:
        print(f"[INFO] Deleting PVC for user: {args.username}")
        run([
            "kubectl", "delete", "pvc",
            "-n", args.namespace,
            pvc_name,
            "--ignore-not-found",
        ], check=False)
        print("[INFO] Done (environment fully reset)")
    else:
        print("[INFO] Done (PVC is preserved)")


def list_users(args: argparse.Namespace) -> None:
    run([
        "kubectl", "get", "pods",
        "-n", args.namespace,
        "-o",
        "custom-columns=NAME:.metadata.name,STATUS:.status.phase,NODE:.spec.nodeName,AGE:.metadata.creationTimestamp",
    ], check=False)


def pvc_list(args: argparse.Namespace) -> None:
    run([
        "kubectl", "get", "pvc",
        "-n", args.namespace,
    ], check=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="JupyterHub admin utility"
    )
    parser.add_argument(
        "-n", "--namespace",
        default=DEFAULT_NAMESPACE,
        help=f"Kubernetes namespace (default: {DEFAULT_NAMESPACE})",
    )
    parser.add_argument(
        "--context",
        dest="kube_context",
        default=None,
        help="kubectl/helm context to use (default: current context)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the commands that would run, without executing them",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_apply = subparsers.add_parser("apply", help="Apply JupyterHub config with Helm")
    p_apply.add_argument(
        "-r", "--release",
        default=DEFAULT_RELEASE,
        help=f"Helm release name (default: {DEFAULT_RELEASE})",
    )
    p_apply.add_argument(
        "-f", "--values",
        default=DEFAULT_VALUES,
        help=f"Values file path (default: {DEFAULT_VALUES})",
    )
    p_apply.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait for hub rollout",
    )
    p_apply.add_argument(
        "--pull",
        metavar="IMAGE",
        nargs="+",
        default=None,
        help="Pre-pull IMAGE(s) on all nodes before applying (uses IfNotPresent afterwards)",
    )
    p_apply.set_defaults(func=lambda args: apply_config(
        argparse.Namespace(
            namespace=args.namespace,
            release=args.release,
            values=args.values,
            wait=not args.no_wait,
            pull=args.pull,
        )
    ))

    p_refresh = subparsers.add_parser("refresh", help="Restart user's server pod, keep PVC")
    p_refresh.add_argument("username", help="JupyterHub username")
    p_refresh.set_defaults(func=lambda args: refresh_user(
        argparse.Namespace(
            namespace=args.namespace,
            username=args.username,
            full=False,
            yes=False,
        )
    ))

    p_refresh_full = subparsers.add_parser(
        "refresh-full",
        help="Delete user's server pod and PVC",
    )
    p_refresh_full.add_argument("username", help="JupyterHub username")
    p_refresh_full.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    p_refresh_full.set_defaults(func=lambda args: refresh_user(
        argparse.Namespace(
            namespace=args.namespace,
            username=args.username,
            full=True,
            yes=args.yes,
        )
    ))

    p_list = subparsers.add_parser("list", help="List JupyterHub user pods")
    p_list.set_defaults(func=list_users)

    p_pvc = subparsers.add_parser("pvc", help="List PVCs")
    p_pvc.set_defaults(func=pvc_list)

    args = parser.parse_args()
    set_kube_context(args.kube_context)
    set_dry_run(args.dry_run)
    args.func(args)


if __name__ == "__main__":
    main()
