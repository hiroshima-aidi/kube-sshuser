# docker-ssh + Kubernetes GPU Job Environment

SSH コンテナイメージと`gpu-dev`ツール。

利用者は SSH でログインし、`gpu-dev` コマンドで GPU 環境に入ります。
ユーザ管理は別のリポジトリで行います。

------------------------------------------------------------------------

## 全体構成

\[User\] → SSH → \[SSH Container\] → sudo gpu-dev →
Kubernetes(namespaceごと)

------------------------------------------------------------------------

## 利用者向け

### ログイン

ssh -p `<PORT>`{=html} `<USER>`{=html}@`<HOST>`{=html}

### gpu-dev Usage

```bash
gpu-dev up [OPTIONS]
gpu-dev down [--name NAME | --all]
gpu-dev status
```

`up` は GPU 開発 Pod を作成または再利用して接続します。
`down` は Pod を削除します。
`status` は自分の gpu-dev Pod 一覧を表示します。

### gpu-dev up オプション

-   --file : `up` オプションを読み込む YAML ファイルパス（CLI指定が優先）
-   --ttl : Pod の生存時間（秒）。デフォルト: 3600
-   --gpu : 使用する GPU 数。デフォルト: 1
-   --image : GPU Pod のコンテナイメージ。デフォルト: nvidia/cuda:12.2.0-runtime-ubuntu22.04
-   --pull : イメージ取得ポリシー（always / if-not-present / never）。デフォルト: if-not-present
-   --name : 論理Pod名（例: test1）。実Pod名は `gpu-dev-<owner>-<name>`
-   --pvc : マウントする PVC 名。デフォルト: workspace
-   --mount-path : コンテナ内マウント先。デフォルト: /workspace
-   --workdir : コンテナ内作業ディレクトリ。デフォルトは `--mount-path`
-   --runtime-class : RuntimeClass 名。デフォルト: nvidia
-   --node-selector : nodeSelector を `KEY=VALUE` 形式で指定。デフォルト: `gpu=true`
-   --cpu-request : CPU request。デフォルト: 2
-   --cpu-limit : CPU limit。デフォルト: 4
-   --memory-request : メモリ request。デフォルト: 8Gi
-   --memory-limit : メモリ limit。デフォルト: 16Gi
-   --env : コンテナ環境変数（`KEY=VALUE`）。複数指定可能
-   --shell : `kubectl exec` で起動するシェル。デフォルト: bash
-   --keep : セッション終了後も Pod を削除せず保持（新規作成時のみ有効）
-   --forward : ポートフォワード指定（`local:remote`）。複数指定可能
  （ServiceAccount に `pods/portforward` の create 権限が必要）

### gpu-dev down オプション

-   --name : 論理Pod名（例: test1）。未指定時は default Pod を対象
-   --all : 自分の gpu-dev Pod を全削除

### 利用例

```bash
# デフォルト設定で接続
gpu-dev up

# YAMLファイルから設定を読み込んで起動
gpu-dev up --file gpu-dev.yaml

# GPU数とTTLを指定して起動
gpu-dev up --gpu 2 --ttl 7200

# イメージとリソースを指定
gpu-dev up \
  --image nvidia/cuda:12.2.0-devel-ubuntu22.04 \
  --cpu-request 4 --cpu-limit 8 \
  --memory-request 16Gi --memory-limit 32Gi

# 論理名をつけてPodを保持
gpu-dev up --name exp1 --keep

# --pull always を使う
gpu-dev up --name exp1 --pull always
# 既存Podがある場合はpull設定は効かないため、先に削除してからupする
gpu-dev down --name exp1 && gpu-dev up --name exp1 --pull always

# シェルと作業ディレクトリを指定
gpu-dev up --shell sh --workdir /workspace/project

# 環境変数を渡す
gpu-dev up --env HF_HOME=/workspace/.cache/hf --env WANDB_MODE=offline

# ポートフォワード（複数可）
gpu-dev up --name exp1 --forward 8888:8888 --forward 6006:6006

# Pod一覧表示
gpu-dev status

# 指定Podを削除
gpu-dev down --name exp1

# 自分のgpu-dev Podを全削除
gpu-dev down --all
```

既存Podがある場合、`up` の作成時オプション（`--gpu` など）は無視され、既存Podへ接続します。
また既存Pod再利用時は `--pull` の設定は反映されません（警告を表示）。

### YAML 設定ファイル例

```yaml
name: exp1
image: nvidia/cuda:12.2.0-devel-ubuntu22.04
pull: always
gpu: 2
ttl: 7200
pvc: workspace
mount-path: /workspace
workdir: /workspace/project
runtime-class: nvidia
node-selector: gpu=true
cpu-request: "4"
cpu-limit: "8"
memory-request: 16Gi
memory-limit: 32Gi
shell: bash
keep: true
env:
  HF_HOME: /workspace/.cache/hf
  WANDB_MODE: offline
forward:
  - 8888:8888
  - 6006:6006
```

### データ保存

/workspace（PVC）

------------------------------------------------------------------------

## ビルド

### SSH コンテナイメージビルド

```bash
make ssh-build IMAGE=docker-ssh:latest
```

------------------------------------------------------------------------

## セキュリティ

-   kubeconfig はユーザに渡さない
-   SSH Pod には admin kubeconfig を配置しない（ServiceAccount トークンで namespace 内 API を利用する設計）

### gpu-dev に必要な最小RBAC（例）

`gpu-dev up --forward ...` を使う場合は、ServiceAccount に
`pods/portforward` の create 権限が必要です。未付与時は port-forward を
スキップし、Pod にはそのまま `exec` で接続します。

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ssh-user-gpu-dev
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/exec", "pods/log", "pods/portforward"]
    verbs: ["get", "list", "watch", "create", "delete"]
```

------------------------------------------------------------------------

## License

MIT
