#!/bin/bash
set -euo pipefail

ensure_line() {
  local line="$1"
  local file="$2"
  touch "$file"
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

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "[entrypoint] error: required env ${name} is not set" >&2
    exit 1
  fi
}

append_or_replace_export() {
  local name="$1"
  local value="$2"
  local file="$3"

  touch "$file"
  if grep -q "^export ${name}=" "$file" 2>/dev/null; then
    sed -i "s|^export ${name}=.*$|export ${name}=${value}|" "$file"
  else
    echo "export ${name}=${value}" >> "$file"
  fi
}

append_if_missing() {
  local line="$1"
  local file="$2"
  touch "$file"
  grep -qxF "$line" "$file" || echo "$line" >> "$file"
}

require_env SSH_USER
require_env SSH_UID
require_env SSH_GID

SSH_GROUP="${SSH_GROUP:-$SSH_USER}"
SSH_PUBLIC_KEY="${SSH_PUBLIC_KEY:-}"
SSH_HOME="/home/${SSH_USER}"
SA_DIR="/var/run/secrets/kubernetes.io/serviceaccount"
KUBECONFIG_PATH="${SSH_HOME}/.kube/config"

if [ -z "${K8S_NAMESPACE:-}" ]; then
  K8S_NAMESPACE="$(normalize_namespace "ns-${SSH_USER}")"
fi
export K8S_NAMESPACE

if ! getent group "$SSH_GROUP" > /dev/null; then
  groupadd -g "$SSH_GID" "$SSH_GROUP"
fi

if ! id "$SSH_USER" > /dev/null 2>&1; then
  useradd -m -d "$SSH_HOME" -u "$SSH_UID" -g "$SSH_GID" -s /bin/bash "$SSH_USER"
fi

mkdir -p "$SSH_HOME"
chmod 755 "$SSH_HOME"

if [ "${SSH_PASSWORD_ENABLED:-no}" = "yes" ] && [ -n "${SSH_PASSWORD_VALUE:-}" ]; then
  echo "${SSH_USER}:$(echo "${SSH_PASSWORD_VALUE}" | openssl passwd -6 -stdin)" | chpasswd
fi

mkdir -p "${SSH_HOME}/.ssh"
chmod 700 "${SSH_HOME}/.ssh"

if [ -n "${SSH_PUBLIC_KEY}" ]; then
  printf '%s\n' "${SSH_PUBLIC_KEY}" > "${SSH_HOME}/.ssh/authorized_keys"
else
  : > "${SSH_HOME}/.ssh/authorized_keys"
fi
chmod 600 "${SSH_HOME}/.ssh/authorized_keys"

mkdir -p "${SSH_HOME}/.kube"
chmod 700 "${SSH_HOME}/.kube"

if [ ! -f "${SA_DIR}/token" ] || [ ! -f "${SA_DIR}/ca.crt" ]; then
  echo "[entrypoint] warning: serviceaccount token or ca.crt is not mounted" >&2
  echo "[entrypoint] warning: kubectl may not work" >&2
else
  if [ -z "${KUBERNETES_SERVICE_HOST:-}" ] || [ -z "${KUBERNETES_SERVICE_PORT:-}" ]; then
    echo "[entrypoint] warning: KUBERNETES_SERVICE_HOST/PORT is not set" >&2
    echo "[entrypoint] warning: ~/.kube/config was not generated" >&2
  else
    cat > "${KUBECONFIG_PATH}" <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: in-cluster
    cluster:
      server: "https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT}"
      certificate-authority: ${SA_DIR}/ca.crt
users:
  - name: sa-user
    user:
      tokenFile: ${SA_DIR}/token
contexts:
  - name: default
    context:
      cluster: in-cluster
      user: sa-user
      namespace: "${K8S_NAMESPACE}"
current-context: default
EOF
    chmod 600 "${KUBECONFIG_PATH}"
  fi
fi

touch "${SSH_HOME}/.bashrc"

append_or_replace_export "K8S_NAMESPACE" "${K8S_NAMESPACE}" "${SSH_HOME}/.bashrc"
append_or_replace_export "KUBECONFIG" "${KUBECONFIG_PATH}" "${SSH_HOME}/.bashrc"

append_if_missing "alias k='kubectl -n \$K8S_NAMESPACE'" "${SSH_HOME}/.bashrc"
append_if_missing 'export PATH="/opt/venv/bin:$PATH"' "${SSH_HOME}/.bashrc"

chown -R "${SSH_USER}:${SSH_GROUP}" "${SSH_HOME}"

sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?ChallengeResponseAuthentication .*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?KbdInteractiveAuthentication .*/KbdInteractiveAuthentication no/' /etc/ssh/sshd_config || true
sed -i 's/^#\?UsePAM .*/UsePAM yes/' /etc/ssh/sshd_config || true

ensure_line "PermitRootLogin no" /etc/ssh/sshd_config
ensure_line "PubkeyAuthentication yes" /etc/ssh/sshd_config
ensure_line "AuthorizedKeysFile .ssh/authorized_keys" /etc/ssh/sshd_config
ensure_line "AllowUsers ${SSH_USER}" /etc/ssh/sshd_config

exec /usr/sbin/sshd -D -e