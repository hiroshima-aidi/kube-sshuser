#!/usr/bin/env python3

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd, check=True, capture_output=True):
    if isinstance(cmd, str):
        shell = True
        printable = cmd
    else:
        shell = False
        printable = " ".join(shlex.quote(str(x)) for x in cmd)

    print(f"[cmd] {printable}", file=sys.stderr)
    return subprocess.run(
        cmd,
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


def docker_rm_if_exists(name: str) -> bool:
    result = run(["docker", "rm", "-f", name], check=False)
    return result.returncode == 0


def kubectl_delete_namespace(namespace: str) -> bool:
    result = run(["kubectl", "delete", "namespace", namespace], check=False)
    return result.returncode == 0


def delete_output_dir(path: Path) -> bool:
    if not path.exists():
        return False
    shutil.rmtree(path)
    return True


def confirm_or_exit(message: str, assume_yes: bool):
    if assume_yes:
        return
    reply = input(f"{message} [y/N]: ").strip().lower()
    if reply not in {"y", "yes"}:
        print("aborted", file=sys.stderr)
        sys.exit(1)


def parse_args():
    p = argparse.ArgumentParser(
        description="Delete one provisioned SSH user environment."
    )
    p.add_argument("--user", required=True, help="logical username, e.g. taro")
    p.add_argument("--namespace", default=None, help="override namespace")
    p.add_argument("--container-name", default=None, help="override docker container name")
    p.add_argument("--out-dir", default="./out", help="base output directory")

    p.add_argument(
        "--keep-namespace",
        action="store_true",
        help="do not delete Kubernetes namespace",
    )
    p.add_argument(
        "--keep-container",
        action="store_true",
        help="do not delete Docker container",
    )
    p.add_argument(
        "--keep-files",
        action="store_true",
        help="do not delete out/<user> generated files",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="do not ask for confirmation",
    )
    return p.parse_args()


def main():
    args = parse_args()

    username = normalize_name(args.user)
    namespace = args.namespace or normalize_name(f"ns-{username}")
    container_name = args.container_name or normalize_name(f"ssh-{username}")
    output_dir = (Path(args.out_dir) / username).resolve()

    summary = {
        "user": username,
        "namespace": namespace,
        "container_name": container_name,
        "output_dir": str(output_dir),
        "delete_container": not args.keep_container,
        "delete_namespace": not args.keep_namespace,
        "delete_files": not args.keep_files,
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    confirm_or_exit("Proceed with deletion?", args.yes)

    deleted = {
        "container_deleted": None,
        "namespace_deleted": None,
        "files_deleted": None,
    }

    if not args.keep_container:
        print("[1/3] deleting docker container...", file=sys.stderr)
        deleted["container_deleted"] = docker_rm_if_exists(container_name)

    if not args.keep_namespace:
        print("[2/3] deleting namespace...", file=sys.stderr)
        deleted["namespace_deleted"] = kubectl_delete_namespace(namespace)

    if not args.keep_files:
        print("[3/3] deleting generated files...", file=sys.stderr)
        deleted["files_deleted"] = delete_output_dir(output_dir)

    result = {
        **summary,
        **deleted,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()