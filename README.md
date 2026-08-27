# kube-tools

研究室の Kubernetes（k3s）運用ツール一式。以前は 4 つの独立したリポジトリに分かれていたものを
1 つに統合したものです。

## 中身

| 場所 | 中身 | 主な利用者 |
|---|---|---|
| `packages/kube_sshuser/` | `kube-sshuser` CLI。ユーザ環境（namespace・PVC・クォータ・SSH 入口）の払い出し | 管理者 |
| `packages/kube_lab/` | `gpu-dev` CLI。PVC をマウントした GPU Pod の起動・停止 | 利用者（学生） |
| `packages/kube_jupyterhub/` | `kube-jupyterhub` CLI。Helm で JupyterHub を管理 | 管理者（別系統） |
| `images/ssh/` | SSH コンテナイメージ（`gpu-dev` を焼き込む） | 管理者 |
| `images/jupyter/` | Jupyter イメージのビルド | 管理者（別系統） |
| `docs/RUNBOOK.md` | 管理者向け運用手順書 | 管理者 |
| `docs/user/kube-lab.md` | 学生向けの `gpu-dev` の使い方 | 利用者（学生） |

**`packages/kube_lab` が SSH イメージに焼き込まれる**のが、これらを 1 つのリポジトリに置く理由です。
別リポジトリだと Dockerfile が「GitHub から pip install」か vendoring になり、ビルドの再現性と、
RBAC（`kube_sshuser` 側）と `gpu-dev` の同時変更のレビューが両方壊れます。

## 全体の流れ

```
[管理者] kube-sshuser create taro ...
             ↓ 作るのは「入れ物」まで
         namespace ns-taro / PVC workspace / ResourceQuota / SA+RBAC / SSH Pod (NodePort 31000-31999)
             ↓
[利用者] ssh -p 31007 taro@<host>
             ↓ SSH コンテナ内で
         gpu-dev up --gpu 1        ← PVC を /workspace にマウントした GPU Pod
```

JupyterHub 系（`kube_jupyterhub` / `images/jupyter`）は SSH 系とは**別系統**です。

## インストール

管理者ツールだけを入れる場合:

```bash
pip install "git+https://github.com/hiroshima-aidi/kube-tools.git#subdirectory=packages/kube_sshuser"
```

開発時は全パッケージを editable で入れます:

```bash
make dev-install
```

## イメージのビルド

```bash
make ssh-build IMAGE=docker-ssh:latest       # SSH イメージ
make ssh-push GITHUB_USER=... GITHUB_TOKEN=...   # ghcr.io へ（.env でも可）
make ssh-build-import                        # ビルド + k3s の containerd へ import

make jupyter-build STACK=cpu WITH_IJULIA=1   # Jupyter イメージ（cpu | cuda12.2 | cuda11.8）
make jupyter-push STACK=cuda12.2 IMAGE_TAG=2026.04.01
make jupyter-help                            # Jupyter 側の全ターゲットと変数
```

イメージ名 `ghcr.io/hiroshima-aidi/ssh-for-k8s` と `ghcr.io/rellab/jupyter-gpu` は
**リポジトリ統合後も変えていません**（稼働中の Deployment の image 参照を壊さないため）。

## ライセンス

MIT。`LICENSE.md` を参照。
