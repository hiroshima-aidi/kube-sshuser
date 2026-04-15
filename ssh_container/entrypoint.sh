#!/bin/bash
set -euo pipefail

SSH_HOME="/home/${SSH_USER}"

ensure_line() {
  local line="$1"
  local file="$2"
  grep -qxF "$line" "$file" || echo "$line" >> "$file"
}

normalize_namespace() {
  local raw="$1"
  echo "$raw" \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9-]/-/g' \
    | sed 's/--*/-/g' \
    | sed 's/^-//' \
    | sed 's/-$//'
}

# K8S_NAMESPACE が未指定なら SSH_USER から自動生成
if [ -z "${K8S_NAMESPACE:-}" ]; then
  K8S_NAMESPACE="$(normalize_namespace "ns-${SSH_USER}")"
fi
export K8S_NAMESPACE

# グループ作成
if ! getent group "$SSH_GROUP" > /dev/null; then
  groupadd -g "$SSH_GID" "$SSH_GROUP"
fi

# ユーザ作成
if ! id "$SSH_USER" > /dev/null 2>&1; then
  useradd -m -d "$SSH_HOME" -u "$SSH_UID" -g "$SSH_GID" -s /bin/bash "$SSH_USER"
fi

# パスワード設定
if [ "${SSH_PASSWORD_ENABLED}" = "yes" ] && [ -n "${SSH_PASSWORD_VALUE}" ]; then
  echo "${SSH_USER}:$(echo "${SSH_PASSWORD_VALUE}" | openssl passwd -6 -stdin)" | chpasswd
fi

# sudo設定（gpu-dev のみ許可）
echo "${SSH_USER} ALL=(root) NOPASSWD: /opt/venv/bin/gpu-dev" > "/etc/sudoers.d/${SSH_USER}"
chmod 440 "/etc/sudoers.d/${SSH_USER}"

# .ssh 設定
mkdir -p "${SSH_HOME}/.ssh"
chmod 700 "${SSH_HOME}/.ssh"

if [ -n "${SSH_PUBLIC_KEY}" ]; then
  printf '%s\n' "${SSH_PUBLIC_KEY}" > "${SSH_HOME}/.ssh/authorized_keys"
else
  : > "${SSH_HOME}/.ssh/authorized_keys"
fi
chmod 600 "${SSH_HOME}/.ssh/authorized_keys"

# 一般ユーザ用 kubeconfig は作らない
mkdir -p "${SSH_HOME}/.kube"
chmod 700 "${SSH_HOME}/.kube"

# admin kubeconfig の存在確認
if [ -n "${K8S_ADMIN_KUBECONFIG:-}" ]; then
  if [ ! -f "${K8S_ADMIN_KUBECONFIG}" ]; then
    echo "[entrypoint] warning: K8S_ADMIN_KUBECONFIG not found at ${K8S_ADMIN_KUBECONFIG}"
  fi
else
  echo "[entrypoint] warning: K8S_ADMIN_KUBECONFIG is not set"
fi

# 必要環境変数を bashrc に見せる
if ! grep -q 'export K8S_NAMESPACE=' "${SSH_HOME}/.bashrc" 2>/dev/null; then
  echo "export K8S_NAMESPACE=${K8S_NAMESPACE}" >> "${SSH_HOME}/.bashrc"
fi

if ! grep -q 'export K8S_SERVER=' "${SSH_HOME}/.bashrc" 2>/dev/null; then
  echo "export K8S_SERVER=${K8S_SERVER:-}" >> "${SSH_HOME}/.bashrc"
fi

if ! grep -q 'export K8S_CA_CERT_B64=' "${SSH_HOME}/.bashrc" 2>/dev/null; then
  echo "export K8S_CA_CERT_B64=${K8S_CA_CERT_B64:-}" >> "${SSH_HOME}/.bashrc"
fi

if ! grep -q 'export K8S_ADMIN_KUBECONFIG=' "${SSH_HOME}/.bashrc" 2>/dev/null; then
  echo "export K8S_ADMIN_KUBECONFIG=${K8S_ADMIN_KUBECONFIG:-}" >> "${SSH_HOME}/.bashrc"
fi

# 使いやすさのため alias を追加
if ! grep -q "alias gpu-dev=" "${SSH_HOME}/.bashrc" 2>/dev/null; then
  echo "alias gpu-dev='sudo /opt/venv/bin/gpu-dev'" >> "${SSH_HOME}/.bashrc"
fi

# 所有権調整
chown -R "${SSH_USER}:${SSH_GROUP}" "${SSH_HOME}"

# sshd_config セキュリティ設定
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?ChallengeResponseAuthentication .*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?UsePAM .*/UsePAM yes/' /etc/ssh/sshd_config || true

ensure_line "PermitRootLogin no" /etc/ssh/sshd_config
ensure_line "PubkeyAuthentication yes" /etc/ssh/sshd_config
ensure_line "AuthorizedKeysFile .ssh/authorized_keys" /etc/ssh/sshd_config
ensure_line "AllowUsers ${SSH_USER}" /etc/ssh/sshd_config

exec /usr/sbin/sshd -D -e