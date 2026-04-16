#!/usr/bin/env python3

import argparse
import json


def parse_image_pull_policy(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    mapping = {
        "always": "Always",
        "if-not-present": "IfNotPresent",
        "ifnotpresent": "IfNotPresent",
        "never": "Never",
    }
    if normalized in mapping:
        return mapping[normalized]
    raise argparse.ArgumentTypeError(
        "--pull must be one of: always, if-not-present, never"
    )


def build_annotations_block(display_name, description, indent: str) -> str:
    annotations = []
    if display_name:
        annotations.append(
            (
                "provision-user.openai.local/display-name",
                json.dumps(display_name, ensure_ascii=False),
            )
        )
    if description:
        annotations.append(
            (
                "provision-user.openai.local/description",
                json.dumps(description, ensure_ascii=False),
            )
        )
    if not annotations:
        return ""

    lines = [f"{indent}annotations:"]
    lines.extend(f"{indent}  {key}: {value}" for key, value in annotations)
    return "\n" + "\n".join(lines)


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
    requests.cpu: \"{args.cpu_quota}\"
    limits.cpu: \"{args.cpu_quota}\"
    requests.memory: \"{args.memory_quota}\"
    limits.memory: \"{args.memory_quota}\"
    requests.storage: \"{args.storage}\"
    persistentvolumeclaims: \"5\"
    requests.nvidia.com/gpu: \"{args.gpu_quota}\"
    limits.nvidia.com/gpu: \"{args.gpu_quota}\"
"""

    namespace_annotations = build_annotations_block(args.display_name, args.description, "  ")
    pod_annotations = build_annotations_block(args.display_name, args.description, "      ")

    return f"""\
apiVersion: v1
kind: Namespace
metadata:
  name: {args.namespace}
  labels:
    app.kubernetes.io/managed-by: provision-user
    provision-user.openai.local/user: {args.username}
{namespace_annotations}
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
  - apiGroups: [\"\"]
    resources: [\"pods\"]
    verbs: [\"get\", \"list\", \"watch\", \"create\", \"delete\"]
  - apiGroups: [\"\"]
    resources: [\"pods/exec\"]
    verbs: [\"create\"]
  - apiGroups: [\"\"]
    resources: [\"pods/portforward\"]
    verbs: [\"create\"]
  - apiGroups: [\"\"]
    resources: [\"pods/log\"]
    verbs: [\"get\", \"list\"]
  - apiGroups: [\"\"]
    resources: [\"persistentvolumeclaims\"]
    verbs: [\"get\", \"list\", \"watch\"]
  - apiGroups: [\"\"]
    resources: [\"events\"]
    verbs: [\"get\", \"list\", \"watch\"]
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
{namespace_annotations}
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
{pod_annotations}
    spec:
      serviceAccountName: {args.service_account_name}
      automountServiceAccountToken: true
      nodeSelector:
        {args.login_node_label_key}: \"{args.login_node_label_value}\"
      terminationGracePeriodSeconds: 30
      containers:
        - name: ssh
          image: {args.image}
          imagePullPolicy: {args.image_pull_policy}
          ports:
            - name: ssh
              containerPort: 22
              hostPort: {args.port}
              protocol: TCP
          env:
            - name: SSH_USER
              value: \"{args.username}\"
            - name: SSH_UID
              value: \"{args.ssh_uid}\"
            - name: SSH_GROUP
              value: \"{args.username}\"
            - name: SSH_GID
              value: \"{args.ssh_gid}\"
            - name: SSH_PUBLIC_KEY
              value: \"{public_key}\"
            - name: K8S_NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
          resources:
            requests:
              cpu: \"{args.ssh_cpu_request}\"
              memory: \"{args.ssh_memory_request}\"
            limits:
              cpu: \"{args.ssh_cpu_limit}\"
              memory: \"{args.ssh_memory_limit}\"
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
