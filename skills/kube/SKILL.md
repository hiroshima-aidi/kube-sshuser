---
name: kube
description: 研究室 Kubernetes クラスタの学生 SSH 環境を kube-sshuser で操作する。新入生への環境払い出し、公開鍵の登録、GPU/CPU/メモリのクォータ変更、ストレージ拡張、稼働状況やGPU使用状況の確認、暴走 Pod の停止、卒業生の環境削除、台帳とクラスタの突き合わせ。ユーザ名や namespace (ns-*) が出てくる管理作業で使う。
---

# kube-sshuser 操作

研究室クラスタの学生 SSH 環境を管理する CLI `kube-sshuser` を操作するためのスキル。

**詳細な手順書は `references/runbook.md`**（リポジトリの `docs/RUNBOOK.md` への symlink）。
このファイルには判断と安全ルールだけを書く。個別の手順が必要になったら
`references/runbook.md` の該当セクションを読むこと。

## 作業を始める前に必ずやること

1. `kubectl config current-context` で **どのクラスタを見ているか** を確認し、ユーザに提示する
2. `kube-sshuser status` で現状を把握する
3. stderr の `[registry] ...` 行を見て、**正しい台帳を使っているか**を確認する
   （`$KUBE_SSHUSER_OUT_DIR` が未設定で `./output` になっていたら、作業前にユーザへ指摘する）

台帳とクラスタの食い違いが疑われるときは `kube-sshuser doctor` を実行する。

## ユースケース

| やりたいこと | コマンド | 手順書 |
|---|---|---|
| 新しい学生に環境を払い出す | `create` | §1 |
| クォータ／ストレージを変える | `modify` | §2 |
| 稼働状況・GPU 使用を見る | `status` / `show` / `list` | §3 |
| 暴走 Pod を止める | `terminate` | §4 |
| 卒業生の環境を消す | `delete` | §5 |
| 公開鍵を差し替える | （専用コマンド無し。回避策あり） | §6 |
| うまくいかない | — | §7 |
| 棚卸し | `doctor` / `status` | §8 |

### 払い出し（create）

必須は `--public-key-file`（または `--public-key-string`）と `--image` の2つ。
**公開鍵とイメージが分からなければ、推測せずユーザに聞く。**
`--name` と `--desc`（学年・所属）も入れるよう促すこと。後の棚卸しで効く。

実行前に必ず `--dry-run` で生成されるマニフェストを確認し、要点（namespace、クォータ、
ストレージ、ノードセレクタ）を日本語で要約してユーザに見せてから本実行する。

NodePort は自動選択されるので `--port` は指定しない（ユーザが明示的に求めた場合のみ）。

完了後は `kube-sshuser show <user>` の Endpoint から接続コマンドを組み立てて伝える。

```
ssh -p <port> <user>@<host>
```

### リソース変更（modify）

`modify` は Pod を再起動しない操作だけを扱う。イメージ・公開鍵・NodePort は変更できない。

**クォータを減らす前には必ず現在の使用量を確認する。** 使用中より小さい値にすると
超過状態になり、学生が新しい Pod を作れなくなる。

```bash
kubectl -n ns-<user> get resourcequota quota -o yaml
```

ストレージは拡張のみ。縮小はできない。

### 状況確認

- `kube-sshuser status` — クラスタ上の全 namespace（実態）
- `kube-sshuser status ns-<user>` — その学生の Pod 一覧
- `kube-sshuser list` / `show <user>` — 台帳（払い出し記録）
- `kube-sshuser doctor` — 台帳とクラスタの突き合わせ

「今誰が使ってる?」は `status`。「いつ誰に払い出した?」は `list` / `show`。

### Pod の停止（terminate）

`owners` に Deployment や Job が出ている Pod は削除しても再作成される。
その場合は controller 側を scale down する必要があることをユーザに伝える。
`--force` は最後の手段。

## 安全ルール

### 削除する前に必ず「消えるもの」を見せる

`delete` は namespace ごと消すため **PVC のデータが失われ、復旧できない**。
Claude が実行する場合、CLI の入力確認を `--yes` で飛ばすことになるので、
その分の確認を必ずチャット上で取ること。手順は固定:

1. `kube-sshuser show <user>` と `kube-sshuser status ns-<user>` を実行する
2. 消えるもの（namespace / PVC 名とサイズ / 稼働中の Pod 数 / 最終更新日）を日本語で提示する
3. 「データは復旧できません。実行してよいですか」と明示的に確認を取る
4. **承認された後に限り** `kube-sshuser delete <user> --yes` を実行する

必要なデータの退避が済んでいるかも確認すること（RUNBOOK §5）。

### やってはいけないこと

- **`--force` を自分の判断で使わない。** これは既存の学生環境の公開鍵とクォータを上書きする。
  「namespace already exists」で止まったら、原因（`--out-dir` 違い / 古い環境の残骸）を
  切り分けてユーザに報告する。RUNBOOK §7.1
- **`kubectl delete` / `kubectl patch` を直接叩かない。** `kube-sshuser` を通すこと。
  台帳と監査ログに記録が残らなくなる
- **`--yes` を確認なしで付けない。** 上記の手順を踏んだ後だけ
- **本番の学生 namespace で試さない。** 動作確認は dummy ユーザで

### 報告の仕方

- 実行したコマンドと結果をそのまま示す。JSON をそのまま貼るのではなく要点を日本語で要約し、
  必要なら生の出力も添える
- 失敗したときは取り繕わない。`kubectl` のエラー本文を見せ、RUNBOOK §7 の該当項目を指す
- 分からないことは推測で埋めない（特に公開鍵、イメージ名、学生の所属）

## 既知の制約（学生に説明が必要になる）

- **`--storage` で確保した PVC はまだ SSH Pod にマウントされていない。** NFS 導入まで保留中。
  ホームディレクトリは Pod の再作成で消える
- ResourceQuota が limits を hard 指定しているため、学生の Pod は requests / limits の
  明示が必要（`must specify limits.cpu` の原因）。RUNBOOK §7.3
- SSH Pod 自身もクォータを消費する（既定で cpu 1 / memory 1Gi）
