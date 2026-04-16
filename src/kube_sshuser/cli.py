#!/usr/bin/env python3

import argparse
import json
import sys

from kube_sshuser import delete_user, provision_user, status
from kube_sshuser.registry import list_user_records, load_user_record


def _fmt(value):
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def show_user(args):
    record = load_user_record(args.out_dir, args.user)
    if not record:
        print(
            f"user record not found: {args.user} (out-dir: {args.out_dir})",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if args.json:
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return

    ssh = record.get("ssh", {})
    ssh_key = record.get("ssh_key", {})
    profile = record.get("profile", {})
    namespace = record.get("namespace", {})
    spec = namespace.get("spec", {})
    requested = spec.get("requested", {})
    observed = spec.get("observed", {})
    last_delete = record.get("last_delete", {})
    paths = record.get("paths", {})

    print(f"User: {_fmt(record.get('user'))}")
    print(f"Name: {_fmt(profile.get('name'))}")
    print(f"Description: {_fmt(profile.get('description'))}")
    print(f"Status: {_fmt(record.get('status'))}")
    print(f"Created At: {_fmt(record.get('created_at'))}")
    print(f"Updated At: {_fmt(record.get('updated_at'))}")
    print(f"Deleted At: {_fmt(record.get('deleted_at'))}")
    print(f"Last Operation: {_fmt(record.get('last_operation_id'))}")
    print()

    print("SSH")
    print(f"  Endpoint: {_fmt(ssh.get('endpoint'))}")
    print(f"  Port: {_fmt(ssh.get('port'))}")
    print(f"  Host IP: {_fmt(ssh.get('host_ip'))}")
    print(f"  Node: {_fmt(ssh.get('node'))}")
    print(f"  Pod: {_fmt(ssh.get('pod'))}")
    print()

    print("SSH Key")
    print(f"  Type: {_fmt(ssh_key.get('type'))}")
    print(f"  Fingerprint: {_fmt(ssh_key.get('fingerprint_sha256'))}")
    print(f"  Comment: {_fmt(ssh_key.get('comment'))}")
    print()

    print("Namespace")
    print(f"  Name: {_fmt(namespace.get('name'))}")
    print()

    print("Namespace Spec (Requested)")
    print(json.dumps(requested, ensure_ascii=False, indent=2))
    print()

    print("Namespace Spec (Observed)")
    print(json.dumps(observed, ensure_ascii=False, indent=2))
    print()

    print("Last Delete")
    print(json.dumps(last_delete, ensure_ascii=False, indent=2))
    print()

    print("Paths")
    print(f"  Output Dir: {_fmt(paths.get('output_dir'))}")
    print(f"  Manifest: {_fmt(paths.get('manifest_path'))}")


def list_users(args):
    records = list_user_records(args.out_dir)
    if args.status:
        records = [r for r in records if r.get("status") == args.status]

    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return

    if not records:
        status_msg = f" with status={args.status}" if args.status else ""
        print(f"no user records found{status_msg} (out-dir: {args.out_dir})")
        return

    grouped = {"active": [], "deleting": [], "deleted": [], "other": []}
    for record in records:
        status = record.get("status")
        if status in grouped and status != "other":
            grouped[status].append(record)
        else:
            grouped["other"].append(record)

    def print_group(name, items):
        if not items:
            return
        print(f"[{name}] {len(items)}")
        for item in sorted(items, key=lambda x: x.get("user", "")):
            user = _fmt(item.get("user"))
            display_name = _fmt(item.get("profile", {}).get("name"))
            namespace = _fmt(item.get("namespace", {}).get("name"))
            endpoint = _fmt(item.get("ssh", {}).get("endpoint"))
            updated_at = _fmt(item.get("updated_at"))
            print(
                f"- user={user} name={display_name} namespace={namespace} endpoint={endpoint} updated_at={updated_at}"
            )
        print()

    print_group("active", grouped["active"])
    print_group("deleting", grouped["deleting"])
    print_group("deleted", grouped["deleted"])
    print_group("other", grouped["other"])


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="kube-sshuser",
        description="Admin CLI for managing SSH users on Kubernetes.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser(
        "create",
        help="provision one user environment",
        description="Provision one namespace + PVC + quota + SA/RBAC + SSH deployment.",
        epilog=(
            "Example: kube-sshuser create taro --name 'Taro Yamada' --desc 'M1 student' "
            "--public-key-file /path/to/key.pub --image ghcr.io/example/image:latest --port 2222"
        ),
    )
    create.add_argument("user", help="logical username, e.g. taro")
    create.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="extra arguments passed to provision-user",
    )

    delete = subparsers.add_parser(
        "delete",
        help="delete one provisioned user environment",
        description="Delete one provisioned SSH user environment.",
    )
    delete.add_argument("user", help="logical username, e.g. taro")
    delete.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="extra arguments passed to delete-user",
    )

    show = subparsers.add_parser(
        "show",
        help="show one user registry record",
        description="Show one user registry record in a readable format.",
    )
    show.add_argument("user", help="logical username, e.g. taro")
    show.add_argument(
        "--out-dir",
        default="./output",
        help="base output directory used by create/delete",
    )
    show.add_argument(
        "--json",
        action="store_true",
        help="print raw JSON instead of formatted text",
    )

    list_cmd = subparsers.add_parser(
        "list",
        help="list user registry records",
        description="List user registry records grouped by status.",
    )
    list_cmd.add_argument(
        "--out-dir",
        default="./output",
        help="base output directory used by create/delete",
    )
    list_cmd.add_argument(
        "--status",
        choices=["active", "deleting", "deleted"],
        help="filter by status",
    )
    list_cmd.add_argument(
        "--json",
        action="store_true",
        help="print raw JSON array instead of formatted text",
    )

    status_cmd = subparsers.add_parser(
        "status",
        help="show managed namespaces and running pods",
        description="Show managed namespaces and pods as a readable table.",
    )
    status_cmd.add_argument(
        "--json",
        action="store_true",
        help="print raw JSON instead of a formatted table",
    )

    return parser.parse_args(argv)


def main(argv=None):
    ns = parse_args(argv)

    if ns.command == "show":
        show_user(ns)
        return

    if ns.command == "list":
        list_users(ns)
        return

    if ns.command == "status":
        forwarded = ["--json"] if ns.json else []
        status.main(forwarded)
        return

    forwarded = ["--user", ns.user, *ns.args]
    if ns.command == "create":
        provision_user.main(forwarded)
        return

    if ns.command == "delete":
        delete_user.main(forwarded)
        return

    raise RuntimeError(f"unsupported command: {ns.command}")


if __name__ == "__main__":
    main()
