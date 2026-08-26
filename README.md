# kube-sshuser

Kubernetes 上でユーザごとの SSH 環境を作成・変更・削除するための管理者向け CLI です。

このリポジトリには kube-sshuser 本体のみを含みます。

## 関連リポジトリと担当範囲

| リポジトリ | 役割 | 使う人 |
|---|---|---|
| **kube-sshuser**（本リポジトリ） | 学生ごとの namespace / PVC / クォータ / SSH 環境の払い出しと管理 | 管理者 |
| [docker-ssh](https://github.com/hiroshima-aidi/docker-ssh) | SSH コンテナイメージと `gpu-dev`（GPU Pod の起動・停止） | 利用者（学生） |
| kube-jupyterhub | JupyterHub の管理 | 管理者（別系統） |
| jupyter-gpu | Jupyter コンテナイメージのビルド | 管理者（別系統） |

**JupyterLab / JupyterHub のデプロイは本リポジトリの対象外**で、kube-jupyterhub が担当します。

本ツールが作るのは「入れ物」（namespace・PVC・クォータ・SSH の入口）までです。
その中で GPU Pod を起動するのは利用者側の `gpu-dev` で、こちらは docker-ssh のドキュメントを参照してください。

## できること

- `kube-sshuser create`: namespace / PVC / ResourceQuota / SA / RBAC / SSH Deployment / NodePort Service を作成
- `kube-sshuser modify`: 稼働中のユーザ環境を Pod を再起動せずに変更（表示名・説明・クォータ・PVC 拡張）
- `kube-sshuser delete`: 作成済み環境の削除
- `kube-sshuser terminate`: namespace 内の pod を単体または一括で削除
- `kube-sshuser show`: ユーザ単位のレジストリ情報表示
- `kube-sshuser list`: レジストリ一覧表示（status フィルタ対応）
- `kube-sshuser status`: 管理対象 namespace の一覧、または namespace 内 pod の稼働状況を表示
- `kube-sshuser doctor`: レジストリとクラスタの食い違い（消えた namespace / 記録の無い namespace / クォータの drift）を検出

ユースケース別の詳しい手順は [docs/RUNBOOK.md](docs/RUNBOOK.md) を参照してください。
Claude Code から操作するための Skill も同梱しています（[導入手順](docs/RUNBOOK.md#9-claude-code-から使う)）。

## 前提条件

- Python 3.9 以上
- `kubectl` が利用可能で、対象クラスタへ apply/delete できる権限があること
- SSH 用コンテナイメージを用意済みであること
- （既定値のまま使う場合）ログインノードに `role=login-server` ラベルがあること

## インストール

> **注意**: 現在の main（v0.5.0）は実クラスタでの検証が未実施です。
> `create --dry-run` でマニフェストを確認してから適用してください。

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

SSH 用 NodePort は `31000-31999` の範囲で自動選択されます。
`--port` で番号を明示することもできます（明示した場合はその番号を使用します）。

```bash
# NodePort 自動選択
kube-sshuser create taro \
	--name "Taro Yamada" \
	--desc "M1 student / CUDA course" \
	--public-key-file /path/to/key.pub \
	--image ghcr.io/hiroshima-aidi/ssh-for-k8s:latest \
	--pull always \
	--storage 100Gi \
	--gpu-quota 1

# NodePort 明示指定
kube-sshuser create taro \
	--name "Taro Yamada" \
	--public-key-file /path/to/key.pub \
	--image ghcr.io/hiroshima-aidi/ssh-for-k8s:latest \
	--port 31005 \
	--storage 100Gi
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

削除は namespace ごと消すため、**PVC に置かれたデータも失われます**。確認プロンプトでは
namespace 名の入力を求めます（`--yes` で省略可）。

```bash
kube-sshuser delete taro
# => 削除対象（context / namespace / PVC / pod 数）が表示され、
#    Type 'ns-taro' to confirm: の入力を求められる

# 非対話（スクリプトから）
kube-sshuser delete taro --yes
```

### Pod の強制終了

```bash
# 単一 pod を強制削除
kube-sshuser terminate ns-taro gpu-dev-taro-exp1 --force --yes

# namespace 内の全 pod を強制削除
kube-sshuser terminate ns-taro --all --force --yes
```

`terminate` は内部的に `kubectl delete pod` を実行します。`--force` を付けると既定で `--grace-period 0 --force` になります。

Pod が Deployment / ReplicaSet / Job などの controller 配下にある場合、削除後に再作成されることがあります。本当に停止したい場合は controller 側を scale down または削除してください。

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
- `--port` (省略時は 31000-31999 から自動選択)
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
- `--dry-run` (適用せず生成マニフェストだけを出力)
- `--login-node-label` (default: `role=login-server`) — ログインノードを選択するラベル
- `--node-address-type` (`ExternalIP` / `InternalIP`, default: `ExternalIP`)
- `--context` (kube-context の明示指定)
- `--yes` (確認プロンプトを省略)
- `--force` (対象 namespace が既にクラスタに存在しても続行＝上書き)

`--out-dir` の既定値は `$KUBE_SSHUSER_OUT_DIR`、未設定時は `./output` です（全サブコマンド共通）。

`kube-sshuser modify <user> ...` の主なオプション:

- `--name` (表示名)
- `--desc` (説明)
- `--gpu-quota` (GPU クォータ)
- `--cpu-quota` (CPU クォータ)
- `--memory-quota` (メモリクォータ)
- `--storage` (PVC 拡張サイズ、縮小不可)
- `--pvc-name` (変更対象 PVC 名、省略時はレジストリから取得)
- `--out-dir`
- `--context`

`kube-sshuser delete <user> ...` の主なオプション:

- `--namespace` (省略時はレジストリの記録値。記録が無い場合のみ `ns-<user>` を推測し、警告を出します)
- `--out-dir`
- `--context`
- `--keep-namespace`
- `--keep-files`
- `--yes` (namespace 名の入力確認を省略)

`kube-sshuser status` の主なオプション:

- `[namespace]` (省略時は namespace 一覧、指定時はその namespace の pod 一覧)
- `--json`
- `--out-dir`
- `--context`

`kube-sshuser doctor` の主なオプション:

- `--out-dir`
- `--context`
- `--json`

食い違いが1件でもあると終了コード 1 を返します。

`kube-sshuser terminate <namespace> <pod> ...` の主なオプション:

- `--all` (namespace 内の全 pod を削除)
- `--force` (強制削除。既定では grace-period 0)
- `--grace-period <seconds>`
- `--yes`
- `--json`
- `--context`

## 出力とレジストリ

`--out-dir` 配下に以下を出力します。

- `<out-dir>/<user>/provision-<user>.yaml`: 生成マニフェスト
- `<out-dir>/_registry/users/<user>.json`: ユーザの最新状態
- `<out-dir>/_registry/events.ndjson`: 監査イベントログ（create / modify / delete を記録）

公開鍵の平文はレジストリに保存せず、`fingerprint_sha256` を記録します。

### out-dir は必ず固定してください

`--out-dir` の既定値は環境変数 `KUBE_SSHUSER_OUT_DIR`、未設定なら `./output` です。
**相対パスのまま運用すると、実行したディレクトリによってレジストリを見失います。**
複数の管理者・複数の踏み台から操作する場合は、共有パスを環境変数で固定してください。

```bash
export KUBE_SSHUSER_OUT_DIR=/srv/kube-sshuser
```

各コマンドは実行時に、実際に使ったレジストリのパスを stderr に出力します。

```
[registry] /srv/kube-sshuser ($KUBE_SSHUSER_OUT_DIR)
```

レジストリを見失った状態で `create` しても、既存 namespace がクラスタ側に居れば
中断します（意図的に上書きする場合のみ `--force`）。

### クラスタの取り違え防止

`create` / `delete` / `terminate` は対象の kube-context を表示してから確認を求めます。
`--context` で明示的に切り替えることもできます。

```bash
kube-sshuser --help                      # サブコマンド一覧
kube-sshuser create taro --context lab-cluster ...
```

## 既知の制約

- **workspace PVC は SSH Pod にはマウントされません。** RWO の multi-attach を避けるため
  意図的にそうしています。PVC は利用者が `gpu-dev up` で起動する GPU Pod に
  `/workspace` としてマウントされます（`gpu-dev --pvc` / `--mount-path`）。
  したがって SSH コンテナ内のホームディレクトリは Pod 再作成で失われます。
  永続させたいデータは `/workspace` に置くよう利用者に周知してください。
- ResourceQuota が `limits.cpu` / `limits.memory` を hard 指定しているため、
  ユーザが namespace 内に作る Pod は requests / limits を明示する必要があります。
- SSH Pod 自身も quota を消費します（既定で cpu limit `1` / memory limit `1Gi`）。
- 公開鍵の変更手段はまだありません（`delete` → `create` はデータ消失を伴います）。

## セキュリティメモ

- SSH Pod は ServiceAccount で in-cluster 認証を利用
- 管理者 kubeconfig を Pod 内へコピーしない前提

## License

MIT
