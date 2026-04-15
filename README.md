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

### GPU 開発環境

gpu-dev\
gpu-dev --gpu 1 --ttl 3600\
gpu-dev --image nvidia/cuda:12.2.0-runtime-ubuntu22.04

### gpu-dev オプション

-   --ttl : Pod の生存時間（秒）
-   --gpu : 使用する GPU 数
-   --image : GPU Pod のコンテナイメージ
-   --name : Pod 名
-   --pvc : PVC 名
-   --mount-path : マウント先

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
