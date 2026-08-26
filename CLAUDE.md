# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`kube-sshuser` は、Kubernetes 上にユーザごとの SSH 環境（namespace / PVC / ResourceQuota / SA+RBAC / Deployment / NodePort Service）を作成・変更・削除する **管理者向け** CLI。README.md は日本語で書かれており、ユーザ向けドキュメントの実体はそちら。

**このツールの担当範囲は「入れ物」まで。** 隣接リポジトリとの境界を取り違えないこと:

- `docker-ssh` — SSH コンテナイメージと `gpu-dev`（利用者が GPU Pod を起動・停止するツール）。本リポジトリが `--image` に指定するのがこのイメージ
- `kube-jupyterhub` — JupyterHub 管理 CLI。**JupyterLab/JupyterHub は本リポジトリの対象外**
- `jupyter-gpu` — Jupyter イメージのビルド

**PVC は SSH Pod にマウントされない。これは意図的な設計。** RWO の multi-attach を避けるため SSH コンテナは入口に徹し、PVC は利用者が `gpu-dev up` で起動する GPU Pod に `/workspace` としてマウントされる（`gpu_dev_pod.py` が `claimName` を指定する）。manifest の Role が pods の create/delete/exec/portforward を許しているのは、SSH コンテナ内から ServiceAccount で `gpu-dev` を動かすため。「PVC が未使用」と誤読しないこと。

## Commands

```bash
# 開発用インストール（Python >= 3.9、ランタイム依存パッケージなし）
python3 -m venv .venv && .venv/bin/pip install -e .

# 実行
.venv/bin/kube-sshuser <create|modify|delete|show|list|status|terminate> ...
python -m kube_sshuser.cli ...   # 同等
```

テストスイート・lint 設定・CI はこのリポジトリには無い。動作確認は実クラスタ（`kubectl` が通る環境）に対して行う前提。マニフェスト生成部分だけは kubectl 無しで確認できる:

```bash
python -c "from kube_sshuser.provision_manifest import build_manifest; ..."
```

リリースは `pyproject.toml` の `version` を上げ、`v0.x.y` というコミットメッセージ 1 本で行うのが慣例（git log 参照）。

## Architecture

**副作用は全て `kubectl` サブプロセス経由。** Kubernetes Python クライアントは使わない。すべての外部実行は `common.run()` を通り、実行コマンドが `[cmd] ...` として stderr に出る。`check=True` での失敗は `common.KubectlError`（コマンド文字列・終了コード・stderr を保持）になり、`common.cli_main()` が各エントリポイントでそれを短いエラーメッセージに変換する。**この例外型は `provision_user.py` の NodePort 衝突リトライが判定に使う**ので、握り潰したり型を変えたりしないこと。JSON 取得は `common.kubectl_get_json()`（失敗時 None）。`status.py` と `terminate_pod.py` は同名のローカル関数を持つが、そちらは失敗時に例外を投げる点が異なる。

**kube-context は `common` のモジュール状態。** 各 `main()` の冒頭で `set_kube_context(args.kube_context)` を呼び、`run()` が `kubectl` 呼び出しに `--context` を注入する。新しいサブコマンドを足すときは `add_context_argument()` と `set_kube_context()` を忘れないこと。

**二層 CLI と、二種類の委譲。** `cli.py` がユーザ向けの argparse フロントエンド。委譲の仕方が 2 通りあるので注意:

- `create` / `delete` は対象モジュールの `build_option_parser()` を argparse の `parents=` で取り込み、パース済み Namespace をそのまま `run_with_args(ns)` に渡す。**オプション定義は各モジュール側の 1 箇所にしかない**ので、追加時に `cli.py` を直す必要はない。
- `modify` / `status` / `terminate` / `doctor` は `cli.py` 側で引数を定義し、argv を組み立て直して `main(argv)` に渡す。こちらは両側に同じ変更が要る。

`show` / `list` だけは kubectl を使わずレジストリを直接読むので `cli.py` 内で完結。

**状態は二重管理。** 真実の状態はクラスタ側にあるが、ローカルにも `--out-dir` 配下のファイルベースのレジストリを持つ。既定値は `common.default_out_dir()`（`$KUBE_SSHUSER_OUT_DIR`、未設定なら `./output`）で、全サブコマンドが `common.add_out_dir_argument()` 経由で統一している:

- `<out-dir>/<user>/provision-<user>.yaml` — 生成マニフェスト
- `<out-dir>/_registry/users/<user>.json` — ユーザ 1 件の最新状態（`status`: active / deleting / deleted）
- `<out-dir>/_registry/events.ndjson` — create / modify / delete の追記型監査ログ

`registry.py` がこの層。書き込みは `update_user_record()`（deep merge + `updated_at` 更新）と `append_event()`。**公開鍵の平文はレジストリに保存しない** — `extract_public_key_metadata()` が type / comment / `fingerprint_sha256` だけを残す。`create` は既存レコードが `status == "active"` なら中断する（再作成には先に `delete`）。

レコードの `namespace.spec` は `requested`（CLI 引数）と `observed`（`collect_observed_namespace_spec()` がクラスタから読み戻した実値）を分けて持つ。この drift 検出用の構造を壊さないこと。

**マニフェストは f-string で生成する（YAML ライブラリではない）。** `provision_manifest.py` の `build_manifest()` が 1 本の複数ドキュメント YAML 文字列を返し、`kubectl apply -f -` に stdin で渡す。人間向けの表示名・説明はアノテーション（`provision-user.openai.local/display-name` / `.../description`）としてインデント指定つきで差し込まれる。値を埋め込む際は `json.dumps()` でクォートするのが既存の流儀。

**識別に使うラベル/アノテーション**（複数モジュールにハードコードされているので変えるときは grep 必須）:

- `app.kubernetes.io/managed-by=provision-user` — `status` が管理対象 namespace を絞る基準
- `app.kubernetes.io/name=ssh-user` + `provision-user.openai.local/user=<user>` — SSH Pod の特定
- `provision-user.openai.local/display-name` / `.../description`

**NodePort は自前で割り当てる。** `--port` 省略時は `get_used_nodeports()` が全 namespace の Service を舐めて 31000–31999 の空きを探す（`provision_kubectl.py`）。

**`modify` は Pod を再起動しない操作だけを扱う。** アノテーション更新 / ResourceQuota の patch / PVC の拡張（縮小不可）に限定されている。イメージ変更など再作成が要るものをここに足さないこと。

**レジストリとクラスタの乖離は `doctor.py` が検出する。** `list`（台帳のみ）と `status`（クラスタのみ）は互いを見ないので、突き合わせはここに集約されている。verdict は `missing-in-cluster` / `orphan-namespace` / `untracked-namespace` / `drift` / `ok`。

**`create --dry-run` はクラスタにもレジストリにも触れない。** `run_with_args()` の冒頭で分岐してマニフェストだけ出力する。この経路が副作用を持たないことが、Claude Code の Skill から「実行前に内容を見せる」運用の前提になっている。

**命名。** namespace は既定で `normalize_name(f"ns-{user}")`（小文字化・非英数をハイフンに・63 文字切り詰め）。

## ドキュメントと Skill

- `docs/RUNBOOK.md` — ユースケース別の運用手順書（日本語）。単一のソース
- `skills/kube/SKILL.md` — Claude Code 用 Skill。判断と安全ルールのみを持ち、詳細は `references/runbook.md`（`docs/RUNBOOK.md` への相対 symlink）に委ねる
- `scripts/install-skill.sh` — `~/.claude/skills/kube` をリポジトリ内 `skills/kube` への symlink にする。`git pull` で CLI・手順書・Skill が同時に更新される設計
- `.claude/settings.json` — 参照系コマンドのみ事前許可。変更系は必ずプロンプトさせる

CLI の挙動を変えたら、`docs/RUNBOOK.md` の該当セクションと `skills/kube/SKILL.md` の安全ルールも合わせて見直すこと。

---

## 現状の記録（2026-08-26 時点／統合リファクタリング前）

研究室の Kubernetes まわりのツールが 4 リポジトリに分かれており、**これらをまとめて
リファクタリングする方針**が出ている。着手する際の前提としてここに記録を残す。

### リポジトリ構成

| リポジトリ | remote | パッケージ / エントリポイント | 最終更新 |
|---|---|---|---|
| admin-tool（本リポジトリ） | `hiroshima-aidi/kube-sshuser` | `kube_sshuser` / `kube-sshuser` | 2026-08-26 |
| docker-ssh | `hiroshima-aidi/ssh-for-k8s` | SSH イメージ + `ssh_tool`（`gpu-dev`） | 2026-04-16 |
| kube-jupyterhub | `hiroshima-aidi/kube-jupyterhub` | `kube_jupyterhub` / `kube-jupyterhub` v0.2.0 | 2026-04-20 |
| jupyter-gpu | `rellab/jupyter-gpu` | Makefile ベースのイメージビルド | 2026-04-20 |

ローカルでは `~/Documents/` 直下に並んでいる。**ディレクトリ名とリポジトリ名が一致していない**
点に注意（`admin-tool` → `kube-sshuser`、`docker-ssh` → `ssh-for-k8s`）。

### 責任分界（現状）

```
[管理者] kube-sshuser create taro ...
             ↓ 作るのは「入れ物」まで
         namespace ns-taro / PVC workspace / ResourceQuota / SA+RBAC / SSH Pod (NodePort)
             ↓
[利用者] ssh -p 31007 taro@<host>          ← SSH イメージは docker-ssh 製
             ↓ SSH コンテナ内で
         gpu-dev up --gpu 1                 ← PVC を /workspace にマウントした GPU Pod
         gpu-dev status / down

[別系統] kube-jupyterhub apply / refresh / list / pvc   ← Helm で JupyterHub を管理
         jupyter-gpu                                     ← Jupyter イメージのビルド
```

- **kube-sshuser と kube-jupyterhub は別系統。** 同じクラスタを使うのかどうか、
  ユーザ・PVC・クォータを共有するのかは **未確認**。統合を検討する際の最初の確認事項。
- `gpu-dev` は SSH コンテナ内から ServiceAccount で kubectl 相当の操作をする。
  そのための RBAC を発行しているのが本リポジトリの `provision_manifest.py`。
  **両者は Role の権限セットで密結合している**（pods の create/delete/exec/portforward、
  pvc の get/list）。片方だけ変えると壊れる。

### 統合を検討する際の論点

1. **ユーザの概念が二重化している。** kube-sshuser は namespace 単位のユーザを台帳で管理し、
   kube-jupyterhub は JupyterHub 側のユーザを持つ。同一人物を両方で払い出す運用なら、
   台帳の一本化が最大の争点になる。
2. **PVC の共有。** kube-sshuser の `workspace` PVC（RWO）と JupyterHub の PVC が別物なら、
   利用者から見て「データが 2 か所にある」状態になる。NFS（購入済み・未対応）を入れる際に
   まとめて設計し直すのが自然。
3. **CLI を統合するか、並置のままにするか。** `kube-sshuser` / `kube-jupyterhub` は
   どちらも kubectl サブプロセス方式で、レジストリの有無だけが違う。共通化するなら
   `common.py`（`run` / `KubectlError` / context / out-dir）が土台になる。
4. **ラベルのドメインが `provision-user.openai.local`。** 研究室のツールとして不適切だが、
   既存クラスタ上のリソースが古いラベルを持つため一括置換は破壊的。統合のタイミングが
   変え時だが、新旧両対応の移行期間が要る。

### 未解決の食い違い

- **`gpu-dev` の sudo 問題は決着済み**（2026-08-26）。`build_summary()` の notes が正しく、
  通常ユーザで実行する。sudo だと `$USER` と `$HOME` が root のものになり、Pod の owner
  ラベルと ServiceAccount の kubeconfig が両方外れる。docker-ssh 側で README の図を直し、
  `warn_if_root()` を追加した。
- 本リポジトリの `docs/RUNBOOK.md` §1 で利用者に伝える `gpu-dev` の使い方は
  docker-ssh の README から書いた。docker-ssh 側が更新されたら追随が要る
  （**現状この 2 つを同期させる仕組みは無い**）。

### 本リポジトリで積み残している改善（レビュー済み・未着手）

`kube-sshuser` 単体のコードレビューで挙がったもののうち、まだ入れていないもの。
統合リファクタリングで一緒に片付ける候補。

- **LimitRange が無い。** ResourceQuota が `limits.cpu` / `limits.memory` を hard 指定して
  いるため、利用者の Pod は requests/limits の明示が必須になり `must specify limits.cpu` で
  弾かれる。namespace に LimitRange を同梱すれば解消する（**利用者体験への影響が最も大きい**）
- **公開鍵の更新手段が無い。** 現状は `kubectl set env deploy/ssh-<user> SSH_PUBLIC_KEY=...`
  という回避策のみで、台帳の fingerprint が更新されない。公開鍵を Secret に移せば
  無停止更新の道が開けるが、docker-ssh のイメージ側の対応が要る
- `modify` のクォータ縮小に事前チェックが無い（使用中より小さい値にできてしまう）
- `--gpu-quota` に負値を渡すと ResourceQuota ごと作られない隠れ仕様（`provision_manifest.py`）
- `list` と `status` の出力形式が不統一（前者は key=value 羅列、後者はテーブル）

### 直近の変更（v0.5.0、未リリース）

ブランチ `harden-and-skill` に以下が入っている。**main には未マージ。**

- 事故要因の修正: NodePort リトライの不発、delete の namespace 推測、create の重複チェック、
  out-dir の cwd 依存、create/delete の help 欠落、context 未表示、delete の確認強化
- 追加: `create --dry-run`、`kube-sshuser doctor`、`docs/RUNBOOK.md`、`skills/kube/`（Claude Code 用 Skill）
- 実クラスタでの検証は未実施（`kubectl apply --dry-run=client` と Skill の実挙動が残っている）
