# kube-sshuser

Kubernetes 上でユーザごとの SSH 環境を作成・削除するための管理者向け CLI です。

このリポジトリには kube-sshuser 本体のみを含みます。

## できること

- `kube-sshuser create`: namespace / PVC / ResourceQuota / SA / RBAC / SSH Deployment を作成
- `kube-sshuser delete`: 作成済み環境の削除
- `kube-sshuser show`: ユーザ単位のレジストリ情報表示
- `kube-sshuser list`: レジストリ一覧表示（status フィルタ対応）
- `kube-sshuser status`: 管理対象 namespace / pod の稼働状況を表形式で表示

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

`/opt/venv` へのインストールは可能です。
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

インストール後、以下のコマンドが使えます（PATH 設定後）。

- `kube-sshuser`

## 使い方

### ユーザ作成

```bash
kube-sshuser create taro --public-key-file /path/to/key.pub --image ghcr.io/hiroshima-aidi/ssh-for-k8s:latest --port 2222
```

`create` は内部処理を呼び出してユーザ環境を作成します。

例:

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

### ユーザ削除

```bash
kube-sshuser delete taro --yes
```

`delete` は内部処理を呼び出してユーザ環境を削除します。

### レジストリ確認

```bash
kube-sshuser show taro
kube-sshuser show taro --json

kube-sshuser list
kube-sshuser list --status active
kube-sshuser list --json

kube-sshuser status
kube-sshuser status --json
```

`status` は Kubernetes クラスタを直接参照し、管理対象 namespace と pod を以下の列で表示します。

namespace ごとに表を分けて表示します。

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
- `--name` (人間向け表示名)
- `--desc` (補足説明)
- `--pull` (`always` / `if-not-present` / `never`, default: `if-not-present`)
- `--port` (必須)
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
- `--login-node-label-key` (default: `role`)
- `--login-node-label-value` (default: `login-server`)
- `--node-address-type` (`ExternalIP` / `InternalIP`, default: `ExternalIP`)

`kube-sshuser delete <user> ...` の主なオプション:

- `--namespace`
- `--out-dir`
- `--keep-namespace`
- `--keep-files`
- `--yes`

`kube-sshuser status` の主なオプション:

- `--json`

## 出力とレジストリ

既定では `--out-dir ./output` 配下に以下を出力します。

- `./output/<user>/provision-<user>.yaml`: 生成マニフェスト
- `./output/_registry/users/<user>.json`: ユーザの最新状態
- `./output/_registry/events.ndjson`: 監査イベントログ

公開鍵の平文はレジストリに保存せず、`fingerprint_sha256` を記録します。

## セキュリティメモ

- SSH Pod は ServiceAccount で in-cluster 認証を利用
- 管理者 kubeconfig を Pod 内へコピーしない前提

## License

MIT
