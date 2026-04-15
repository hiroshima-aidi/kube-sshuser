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
gpu-dev [OPTIONS]
```

デフォルトでは、利用者ごとの GPU 開発 Pod に接続し、終了時に新規作成Podのみ削除します。

### gpu-dev オプション

-   --ttl : Pod の生存時間（秒）。デフォルト: 3600
-   --gpu : 使用する GPU 数。デフォルト: 1
-   --image : GPU Pod のコンテナイメージ。デフォルト: nvidia/cuda:12.2.0-runtime-ubuntu22.04
-   --name : 論理Pod名（例: test1）。実Pod名は `gpu-dev-<owner>-<name>`
-   --pvc : マウントする PVC 名。デフォルト: workspace
-   --mount-path : コンテナ内マウント先。デフォルト: /workspace
-   --runtime-class : RuntimeClass 名。デフォルト: nvidia
-   --node-label-key : nodeSelector のキー。デフォルト: gpu
-   --node-label-value : nodeSelector の値。デフォルト: true
-   --cpu-request : CPU request。デフォルト: 2
-   --cpu-limit : CPU limit。デフォルト: 4
-   --memory-request : メモリ request。デフォルト: 8Gi
-   --memory-limit : メモリ limit。デフォルト: 16Gi
-   --keep : セッション終了後も Pod を削除せず保持（新規作成時のみ有効）
-   --forward : ポートフォワード指定（`local:remote`）。複数指定可能
-   --list : 自分の gpu-dev Pod 一覧を表示して終了
-   --delete : 対象 gpu-dev Pod を削除して終了
-   --delete-all : 自分の gpu-dev Pod を全削除して終了

### 利用例

```bash
# デフォルト設定で接続
gpu-dev

# GPU数とTTLを指定して起動
gpu-dev --gpu 2 --ttl 7200

# イメージとリソースを指定
gpu-dev \
  --image nvidia/cuda:12.2.0-devel-ubuntu22.04 \
  --cpu-request 4 --cpu-limit 8 \
  --memory-request 16Gi --memory-limit 32Gi

# 論理名をつけてPodを保持
gpu-dev --name exp1 --keep

# ポートフォワード（複数可）
gpu-dev --name exp1 --forward 8888:8888 --forward 6006:6006

# Pod一覧表示
gpu-dev --list

# 指定Podを削除
gpu-dev --name exp1 --delete

# 自分のgpu-dev Podを全削除
gpu-dev --delete-all
```

既存Podがある場合、`--gpu` などの作成時リソースオプションは無視され、既存Podへ接続します。

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

------------------------------------------------------------------------

## License

MIT
