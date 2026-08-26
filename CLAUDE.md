# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`kube-sshuser` は、Kubernetes 上にユーザごとの SSH 環境（namespace / PVC / ResourceQuota / SA+RBAC / Deployment / NodePort Service）を作成・変更・削除する管理者向け CLI。README.md は日本語で書かれており、ユーザ向けドキュメントの実体はそちら。

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
