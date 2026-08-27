# kube-lab — クラスタ上に自分の作業環境を立てる

SSH でログインし、`kube-lab` コマンドで GPU 環境に入ります。
ユーザの払い出し（namespace・PVC・SSH の入口）は管理者の `kube-sshuser` が行います。

> **`gpu-dev` から `kube-lab` に改名しました**（2026-08-27、v0.3.0）。
> `gpu-dev` も**今学期いっぱいは今までどおり動きます**。実行すると改名を知らせる
> 1 行が出るだけで、動作は同じです。学期末に `gpu-dev` は削除される予定なので、
> 手元のメモは `kube-lab` に直しておいてください。
>
> Pod のラベル `app=gpu-dev` とアノテーション `gpu-dev/*` は**変わっていません**。
> `kubectl get pods -l app=gpu-dev` は今までどおり動きます。

------------------------------------------------------------------------

## 全体構成

\[User\] → SSH → \[SSH Container\] → kube-lab →
Kubernetes(namespaceごと)

`kube-lab` は **SSH でログインした通常ユーザのまま** 実行します（sudo は不要です）。
sudo を付けると `$USER` と `$HOME` が root のものになり、Pod の owner ラベルと
ServiceAccount の kubeconfig の両方が外れて動きません。

------------------------------------------------------------------------

## 利用者向け

### ログイン

ssh -p `<PORT>`{=html} `<USER>`{=html}@`<HOST>`{=html}

### kube-lab Usage

```bash
kube-lab up [OPTIONS]
kube-lab down [--name NAME | --all]
kube-lab status
```

`up` は GPU 開発 Pod を作成または再利用して接続します。
`down` は Pod を削除します。
`status` は自分の kube-lab Pod 一覧を表示します。

### kube-lab up オプション

-   --file : `up` オプションを読み込む YAML ファイルパス（CLI指定が優先）
-   --ttl : Pod の生存時間（秒）。デフォルト: 3600
-   --gpu : 使用する GPU 数。デフォルト: 1
-   --image : GPU Pod のコンテナイメージ。デフォルト: nvidia/cuda:12.2.0-runtime-ubuntu22.04
-   --pull : イメージ取得ポリシー（always / if-not-present / never）。デフォルト: if-not-present
-   --name : 論理Pod名（例: test1）。実Pod名は `kube-lab-<owner>-<name>`
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

### kube-lab down オプション

-   --name : 論理Pod名（例: test1）。未指定時は default Pod を対象
-   --all : 自分の kube-lab Pod を全削除

### 利用例

```bash
# デフォルト設定で接続
kube-lab up

# YAMLファイルから設定を読み込んで起動
kube-lab up --file kube-lab.yaml

# GPU数とTTLを指定して起動
kube-lab up --gpu 2 --ttl 7200

# イメージとリソースを指定
kube-lab up \
  --image nvidia/cuda:12.2.0-devel-ubuntu22.04 \
  --cpu-request 4 --cpu-limit 8 \
  --memory-request 16Gi --memory-limit 32Gi

# 論理名をつけてPodを保持
kube-lab up --name exp1 --keep

# --pull always を使う
kube-lab up --name exp1 --pull always
# 既存Podがある場合はpull設定は効かないため、先に削除してからupする
kube-lab down --name exp1 && kube-lab up --name exp1 --pull always

# シェルと作業ディレクトリを指定
kube-lab up --shell sh --workdir /workspace/project

# 環境変数を渡す
kube-lab up --env HF_HOME=/workspace/.cache/hf --env WANDB_MODE=offline

# ポートフォワード（複数可）
kube-lab up --name exp1 --forward 8888:8888 --forward 6006:6006

# Pod一覧表示
kube-lab status

# 指定Podを削除
kube-lab down --name exp1

# 自分の Pod を全削除
kube-lab down --all
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

### kube-lab に必要な最小RBAC（例）

`kube-lab up --forward ...` を使う場合は、ServiceAccount に
`pods/portforward` の create 権限が必要です。未付与時は port-forward を
スキップし、Pod にはそのまま `exec` で接続します。

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ssh-user-kube-lab
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/exec", "pods/log", "pods/portforward"]
    verbs: ["get", "list", "watch", "create", "delete"]
```

------------------------------------------------------------------------

## License

MIT
