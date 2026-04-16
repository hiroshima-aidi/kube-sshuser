# kube-sshuser

Kubernetes 上でユーザごとの SSH 環境を作成・変更・削除するための管理者向け CLI です。

このリポジトリには kube-sshuser 本体のみを含みます。

## できること

- `kube-sshuser create`: namespace / PVC / ResourceQuota / SA / RBAC / SSH Deployment を作成
- `kube-sshuser modify`: 稼働中のユーザ環境を Pod を再起動せずに変更（表示名・説明・クォータ・PVC 拡張）
- `kube-sshuser delete`: 作成済み環境の削除
- `kube-sshuser show`: ユーザ単位のレジストリ情報表示
- `kube-sshuser list`: レジストリ一覧表示（status フィルタ対応）
- `kube-sshuser status`: 管理対象 namespace の一覧、または namespace 内 pod の稼働状況を表示

## 前提条件

- Python 3.9 以上
- `kubectl` が利用可能で、対象クラスタへ apply/delete できる権限があること
- SSH 用コンテナイメージを用意済みであること
- （既定値のまま使う場合）ログインノードに `role=login-server` ラベルがあること

## インストール

### 1) 通常インストール

```bash
pip install "git+https://github.com/hiroshima-aidi/kube-sshuser.git"
```

### 2) /opt/venv にインストールする場合

`/opt` 配下の作成に権限が必要な環境では `sudo` を付けてください。

```bash
sudo python3 -m venv /opt/venv
sudo /opt/venv/bin/pip install --upgrade pip
sudo /opt/venv/bin/pip install "git+https://github.com/hiroshima-aidi/kube-sshuser.git"
```

実行パスを通すには、以下を設定します。

```bash
export PATH="/opt/venv/bin:$PATH"
```

永続化する場合（bash）:

```bash
echo 'export PATH="/opt/venv/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

## 使い方

### ユーザ作成

既存のアクティブなユーザに同じ名前で `create` を実行するとエラーで停止します。
変更したい場合は `modify`、再作成したい場合は先に `delete` してください。

```bash
kube-sshuser create taro \
	--name "Taro Yamada" \
	--desc "M1 student / CUDA course" \
	--public-key-file /path/to/key.pub \
	--image ghcr.io/hiroshima-aidi/ssh-for-k8s:latest \
	--pull always \
	--port 2222 \
	--storage 100Gi \
	--gpu-quota 1
```

### ユーザ変更

Pod を再起動せずに変更できるフィールドのみ対象です。
`--name` / `--desc` はアノテーションの更新、`--gpu-quota` / `--cpu-quota` / `--memory-quota` は ResourceQuota の patch、`--storage` は PVC の拡張（縮小不可）です。

```bash
# 表示名・説明の変更
kube-sshuser modify taro --name "Taro Yamada" --desc "M2 student"

# クォータの変更
kube-sshuser modify taro --gpu-quota 2 --memory-quota 128Gi --cpu-quota 32

# PVC 拡張
kube-sshuser modify taro --storage 200Gi

# 組み合わせ自由
kube-sshuser modify taro --name "Taro Yamada" --gpu-quota 4 --storage 200Gi
```

### ユーザ削除

```bash
kube-sshuser delete taro --yes
```

### レジストリ確認

```bash
kube-sshuser show taro
kube-sshuser show taro --json

kube-sshuser list
kube-sshuser list --status active
kube-sshuser list --json

kube-sshuser status
kube-sshuser status ns-taro
kube-sshuser status --json
```

`status` は Kubernetes クラスタを直接参照し、`app.kubernetes.io/managed-by=provision-user` が付いた namespace を対象に動作します。

`kube-sshuser status` は namespace 一覧を表示します。

- `NAMESPACE`
- `AGE`
- `PORT`
- `PODS`
- `CPU`
- `MEM`
- `GPU`
- `STORAGE`
- `DISPLAY NAME`
- `DESCRIPTION`

`CPU` / `MEM` / `GPU` / `STORAGE` は namespace の ResourceQuota から表示します。

`kube-sshuser status <namespace>` は、その namespace 内の Pod 一覧を表示します。

- `NAME`
- `STATUS`
- `AGE`
- `NODE`
- `GPU`
- `CPU`
- `MEM`

## 主なオプション

`kube-sshuser create <user> ...` の主なオプション:

- `--public-key-file` / `--public-key-string` (どちらか必須)
- `--image` (必須)
- `--port` (必須)
- `--name` (人間向け表示名)
- `--desc` (補足説明)
- `--pull` (`always` / `if-not-present` / `never`, default: `if-not-present`)
- `--storage` (default: `100Gi`)
- `--pvc-name` (default: `workspace`)
- `--gpu-quota` (default: `1`)
- `--cpu-quota` (default: `16`)
- `--memory-quota` (default: `64Gi`)
- `--ssh-uid`, `--ssh-gid`
- `--ssh-cpu-request`, `--ssh-cpu-limit`
- `--ssh-memory-request`, `--ssh-memory-limit`
- `--namespace`
- `--out-dir` (default: `./output`)
- `--login-node-label` (default: `role=login-server`) — ログインノードを選択するラベル
- `--node-address-type` (`ExternalIP` / `InternalIP`, default: `ExternalIP`)

`kube-sshuser modify <user> ...` の主なオプション:

- `--name` (表示名)
- `--desc` (説明)
- `--gpu-quota` (GPU クォータ)
- `--cpu-quota` (CPU クォータ)
- `--memory-quota` (メモリクォータ)
- `--storage` (PVC 拡張サイズ、縮小不可)
- `--pvc-name` (変更対象 PVC 名、省略時はレジストリから取得)
- `--out-dir` (default: `./output`)

`kube-sshuser delete <user> ...` の主なオプション:

- `--namespace`
- `--out-dir`
- `--keep-namespace`
- `--keep-files`
- `--yes`

`kube-sshuser status` の主なオプション:

- `[namespace]` (省略時は namespace 一覧、指定時はその namespace の pod 一覧)
- `--json`

## 出力とレジストリ

既定では `--out-dir ./output` 配下に以下を出力します。

- `./output/<user>/provision-<user>.yaml`: 生成マニフェスト
- `./output/_registry/users/<user>.json`: ユーザの最新状態
- `./output/_registry/events.ndjson`: 監査イベントログ（create / modify / delete を記録）

公開鍵の平文はレジストリに保存せず、`fingerprint_sha256` を記録します。

## セキュリティメモ

- SSH Pod は ServiceAccount で in-cluster 認証を利用
- 管理者 kubeconfig を Pod 内へコピーしない前提

## License

MIT
