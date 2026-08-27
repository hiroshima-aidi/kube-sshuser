# kube-jupyterhub

CLI tool for managing JupyterHub on Kubernetes (k3s compatible).

## Installation

Install from GitHub:

```bash
pip install git+https://github.com/hiroshima-aidi/kube-jupyterhub.git
```

Or for development:

```bash
git clone https://github.com/hiroshima-aidi/kube-jupyterhub.git
cd kube-jupyterhub
pip install -e .
```

## Requirements

- Python 3.9+
- `kubectl` configured and accessible
- `helm` configured and accessible
- JupyterHub Helm chart installed

## Usage

### Basic Commands

```bash
# Apply JupyterHub config with Helm
kube-jupyterhub apply

# List all user pods
kube-jupyterhub list

# List PVCs
kube-jupyterhub pvc

# Refresh a user's pod (restart, keep PVC)
kube-jupyterhub refresh <username>

# Fully reset a user (delete pod + PVC)
kube-jupyterhub refresh-full <username>
```

### Options

```bash
# Use custom namespace (default: jupyterhub)
kube-jupyterhub -n custom-namespace apply

# Use custom Helm release name (default: jupyterhub)
kube-jupyterhub apply -r my-release

# Use custom values file (default: config.yaml)
kube-jupyterhub apply -f path/to/values.yaml

# Don't wait for hub rollout to complete
kube-jupyterhub apply --no-wait

# Pre-pull notebook image(s) on all nodes before applying
kube-jupyterhub apply --pull myregistry/notebook:latest
kube-jupyterhub apply --pull myregistry/notebook:latest myregistry/gpu-notebook:v2

# Skip confirmation for dangerous operations
kube-jupyterhub refresh-full <username> --yes
```

## Commands Reference

### `apply`
Apply JupyterHub configuration using Helm.
- `-r, --release`: Helm release name (default: `jupyterhub`)
- `-f, --values`: Values file path (default: `config.yaml`)
- `--no-wait`: Skip waiting for hub deployment rollout
- `--pull IMAGE [IMAGE ...]`: Pre-pull image(s) on all nodes before applying. Deploys a temporary DaemonSet to pull each image, waits for completion on all nodes, then removes it. The singleuser image pull policy remains `IfNotPresent`, so subsequent pod spawns use the cache.

### `list`
List all JupyterHub user pods with status, node, and creation timestamp.

### `pvc`
List all PersistentVolumeClaims in the namespace.

### `refresh <username>`
Restart a user's server pod while preserving their PVC and data.

### `refresh-full <username>`
Completely reset a user (delete pod and PVC). **This deletes all data.**
- `-y, --yes`: Skip confirmation prompt

## Examples

```bash
# Apply config with default settings
kube-jupyterhub apply

# Apply with wait disabled
kube-jupyterhub apply --no-wait

# Pre-pull a single image on all nodes, then apply
kube-jupyterhub apply --pull myregistry/notebook:latest

# Pre-pull multiple images on all nodes, then apply
kube-jupyterhub apply --pull myregistry/notebook:latest myregistry/gpu-notebook:v2

# List users in default namespace
kube-jupyterhub list

# List user in custom namespace
kube-jupyterhub -n my-namespace list

# Restart a user's pod
kube-jupyterhub refresh alice

# Reset user with data deletion (with confirmation)
kube-jupyterhub refresh-full bob

# Reset user with data deletion (skip confirmation)
kube-jupyterhub refresh-full bob -y
```

## Configuration

The default values file location is `config.yaml` in your current directory. You can specify a different location using the `-f` flag:

```bash
kube-jupyterhub apply -f /etc/jupyterhub/values.yaml
```

## License

MIT

## Contributing

Contributions welcome! Please submit issues and pull requests.
