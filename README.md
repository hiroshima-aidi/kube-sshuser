# docker-ssh + Kubernetes GPU Job Environment

SSH でログインし、簡単なコマンドで GPU Pod / Job を実行できる環境です。

-   管理者：ユーザごとの namespace / PVC / SSH コンテナを自動作成
-   利用者：`gpu-dev` コマンドで GPU 環境に入る

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

## 管理者向け

### セットアップ

make admin-install

### イメージビルド

make ssh-build IMAGE=docker-ssh:latest

### ユーザ作成

provision-user --user taro --public-key-file /path/to/key.pub --image
docker-ssh:latest --port 2222

### provision-user オプション

-   --user : ユーザ名
-   --public-key-file : 公開鍵ファイル
-   --public-key-string : 公開鍵文字列
-   --image : SSH コンテナイメージ
-   --port : SSH ポート
-   --storage : PVC サイズ
-   --gpu-quota : GPU 制限
-   --cpu-quota : CPU 制限
-   --memory-quota : メモリ制限

------------------------------------------------------------------------

## セキュリティ

-   kubeconfig はユーザに渡さない
-   kubectlは禁止
-   sudoはgpu-devのみ

------------------------------------------------------------------------

## License

MIT
