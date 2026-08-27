# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**利用者（学生）側**のリポジトリ。成果物は 2 つだけ:

1. SSH コンテナイメージ（`ghcr.io/hiroshima-aidi/ssh-for-k8s`）— 学生がログインする入口
2. その中に入っている `kube-lab` CLI（Python パッケージ `ssh-tool`）— GPU Pod を起こして exec で入るツール

**ユーザの払い出しは本リポジトリの担当外。** namespace / PVC / ResourceQuota / SA+RBAC / SSH Deployment を
作るのは管理者側の `kube-sshuser`（`hiroshima-aidi/kube-sshuser`、ローカルでは `../admin-tool`）。
本リポジトリはそれが用意した環境の中で動くだけ。README.md は日本語で、利用者向けドキュメントの実体はそちら。

隣接リポジトリの全体像は `../CLAUDE.md` を参照。

## Commands

```bash
make ssh-build IMAGE=docker-ssh:latest           # docker build
make ssh-buildx                                  # buildx でビルドしてローカルに load
make ssh-push GITHUB_USER=... GITHUB_TOKEN=...   # ghcr.io へ push（.env でも可）
make ssh-import IMAGE=docker-ssh:latest          # docker save | k3s ctr images import
make ssh-build-import                            # build + import（k3s ノード上での定番）
make clean                                       # __pycache__ / *.egg-info の掃除
```

- **ビルドコンテキストはリポジトリルート**（`-f images/ssh/Dockerfile .`）。Dockerfile 内は
  `COPY packages/ /build/packages/` と書き、`packages/kube_lab` を wheel にする。
  `packages/` を丸ごと入れるのは、Phase 3 で共通コア `kubelab_core` を同じ venv に入れるため。
- push の認証は `GITHUB_USER` / `GITHUB_TOKEN`。ルートの `.env` が Makefile から自動 include される
  （`.env.example` 参照。`.env` はコミットしない）。
- テスト・lint・CI は無い。動作確認は実際にイメージをビルドして k3s 上の SSH Pod で `kube-lab` を叩く。
- リリースは `packages/kube_lab/pyproject.toml` の `version` を上げて `v0.x.y` というコミットメッセージ 1 本、が慣例。

## SSH イメージ

Dockerfile は 2 ステージ（builder で wheel をビルド → final に `/opt/venv` としてインストール）。
final は debian:bookworm-slim + openssh-server + `kubectl`（**バージョン固定で curl 取得**、
`v1.34.1`。クラスタを上げたらここも上げる）。

**`entrypoint.sh` が実質すべて。** Pod 起動のたびに環境変数から状態を組み立てる:

- 必須 env: `SSH_USER` / `SSH_UID` / `SSH_GID`。省略可: `SSH_GROUP` / `SSH_PUBLIC_KEY` /
  `SSH_PASSWORD_ENABLED` + `SSH_PASSWORD_VALUE` / `K8S_NAMESPACE`
- `K8S_NAMESPACE` 未指定なら `normalize_namespace("ns-$SSH_USER")` で導出する。
  **この正規化規則は kube-sshuser 側の `normalize_name()` と重複実装**なので、片方だけ変えると
  namespace 名がずれる。
- **公開鍵は env 経由で `authorized_keys` に書かれる。** つまり鍵の更新 = Deployment の env 差し替え
  = Pod 再作成。Secret 化は admin-tool 側の積み残し課題で、やるならイメージ側の対応も要る。
- **ServiceAccount トークンから in-cluster kubeconfig を生成する**（`~/.kube/config`、
  `tokenFile` 参照、current-context の namespace は `K8S_NAMESPACE`）。`kube-lab` の kubectl 権限は
  すべてここ経由で、その中身は kube-sshuser が発行する Role が決めている。
- `.bashrc` に `KUBECONFIG` / `K8S_NAMESPACE` の export、`alias k=`、`/opt/venv/bin` の PATH を追記
- sshd は毎回 `sshd_config` を書き換えて公開鍵のみ・root 禁止・`AllowUsers $SSH_USER` に固める

## kube-lab（`packages/kube_lab/src/kube_lab/`）

エントリポイントは `kube-lab` と `gpu-dev`（旧名、今学期のみ並走）の 2 つで、どちらも `kube_lab.lab_cli:main`。依存は PyYAML のみ（`--file` のときだけ遅延 import）。

**副作用はすべて `kubectl` サブプロセス。** Kubernetes Python クライアントは使わない。
`lab_k8s.run()` が実行コマンドを `[cmd] ...` として表示する。この方式は kube-sshuser と同じ流儀。

モジュール構成（`lab_core.py` は再エクスポートするだけのハブで、ロジックを持たない）:

- `lab_cli.py` — argparse、`--file` の YAML マージ、`up` の本体フロー
- `lab_pod.py` — Pod マニフェスト生成と `ensure_pod()`
- `lab_k8s.py` — kubectl ラッパ（apply / exists / phase / delete / port-forward）
- `lab_identity.py` — owner・Pod 名・namespace の決定
- `lab_listing.py` — `status` の表示整形
- `lab_defaults.py` — 既定値の**唯一の定義場所**

**識別の規約**（変えるなら全部まとめて）:

- owner = `$USER`（無ければ `$LOGNAME`）を `sanitize_k8s_name()` にかけたもの。**k8s の認証主体ではなく
  シェルの環境変数**なので、sudo 経由だと owner が変わり、自分の Pod が見えなくなる
- Pod 名 = `kube-lab-<owner>` / `--name` 指定時は `kube-lab-<owner>-<name>`
- ラベル `app=gpu-dev` + `owner=<owner>` + `logical-name=`。`down --all` と `status` はこのラベルで絞る

## 改名（Phase 2.5、2026-08-27）

**CLI 名は `gpu-dev` → `kube-lab`、モジュールは `ssh_tool` → `kube_lab`、
ファイルは `gpu_dev*.py` → `lab_*.py`、配布名は `ssh-tool` → `kube-lab`（v0.3.0）。**

`gpu-dev` は実態と合っていなかった。`--gpu 0` でも動くので GPU 専用ではなく、`--name` で
複数 Pod を立てられるので「開発用の 1 個」でもない。実体はクラスタ上に自分の作業環境を
立てるツール。

- **エイリアス並走。** `[project.scripts]` に `kube-lab` と `gpu-dev` の両方を同じ `main()` で
  登録してある。`gpu-dev` で起動したときだけ stderr に改名を知らせる 1 行が出る
  （`naming.warn_if_legacy_name()`）。**1 学期並走させてから `gpu-dev` を削除する。**
- **メッセージ prefix と提案コマンドは起動名に追随する**（`naming.py` の `TAG` / `PROG`）。
  `gpu-dev` で起動した人に `kube-lab down` を勧めると、その人の手元のメモに無いコマンドを
  案内することになるため。
- **ラベル `app: gpu-dev` とアノテーション `gpu-dev/*` は変えていない。** 稼働中の Pod が
  持っており、`down --all` / `status` のセレクタ（`lab_k8s.py:80`, `lab_listing.py:142`）が
  依存している。置換は Phase 6。`build_pod_manifest()` の出力は改名の前後でバイト一致を確認済み。
- namespace は env `K8S_NAMESPACE`。未設定なら即エラー終了（entrypoint が設定している前提）

**`up` のライフサイクル**（`lab_cli.py:main`）:

```
ensure_pod() → 無ければ manifest を apply + wait Ready（180s）
             → あれば再利用（作成時フラグは無視され、warning が出る）
start_port_forward() → kubectl exec -it <pod> -- <shell>
finally: port-forward を止め、"このコマンドで新規作成した" かつ --keep でない場合のみ Pod を削除
```

- **既存 Pod を再利用したときは削除しない。** 削除するのは自分が作った Pod だけ。
- TTL は `command: ["bash","-c","sleep <ttl>"]` として実装されている。**Pod の GC も
  restartPolicy: Never なので、sleep が明けた Pod は Completed のまま残る**（`down` で消す）。
- `main()` は kubectl 実行前に **環境から `KUBECONFIG` を落とす**（`env.pop("KUBECONFIG")`）。
  kubectl は `$HOME/.kube/config` にフォールバックする前提。HOME が変わる実行方法（sudo など）を
  想定した変更を入れるときはここを見ること。
- port-forward は事前に `kubectl auth can-i create pods/portforward` を見て、
  不可なら警告して**黙ってスキップし本体は続行する**（失敗させない）。

**Pod マニフェストは f-string + textwrap.dedent で組む**（`build_pod_manifest()`、YAML ライブラリではない）。
GPU は `nvidia.com/gpu` limit、`runtimeClassName: nvidia`、`nodeSelector` 既定は `gpu=true`。
PVC（既定 `workspace`）を `/workspace` にマウントする — **この PVC を作るのは kube-sshuser**。
env の値だけはエスケープ処理があるが、他のフィールドはそのまま埋め込まれる。

**`--file` のマージ規則に癖がある**（`apply_up_file_config()`）。「CLI が優先」は
「**CLI の値が既定値と異なるときだけ優先**」として実装されているので、CLI で既定値と同じ値を
明示的に渡すと YAML 側に上書きされる。既定値を `lab_defaults.py` で変えると、この判定
（`has_non_default_create_flags()` も同じ方式）の挙動も一緒に動く点に注意。

## 未解決の食い違い

- `lab_cli.py:main()` の `env.pop("KUBECONFIG")` は、`entrypoint.sh` が `KUBECONFIG` を
  kubectl の既定パスと同じ `$HOME/.kube/config` に設定しているため**実質何もしていない**。
  sudo 運用の名残と思われる。

## 決着済み

- **`Makefile` の残骸を削除した**（Phase 1）。`ADMIN_DIR` / `VENV` / `venv` / `admin-install`
  / `clean-venv` は、もう存在しない `admin_tool/` を指していた。管理ツールは kube-sshuser へ
  分離済み。`make -n` の出力は削除の前後で完全一致（＝ビルド挙動は不変）。
- **`kube-lab` は sudo ではなく通常ユーザで実行する。** owner を `$USER` から取り、
  kubeconfig が SSH ユーザの `$HOME` にあるため、sudo だと両方外れる。README の図から
  sudo を削り、`warn_if_root()` で root 実行時に警告を出すようにした。
