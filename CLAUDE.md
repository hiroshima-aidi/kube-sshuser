# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## このリポジトリの性質

`hiroshima-aidi/kube-tools` は、研究室の Kubernetes 運用ツールを 1 つにまとめた**モノレポ**。
以前は 4 つの独立したリポジトリだった（`admin-tool` = kube-sshuser、`docker-ssh` = ssh-for-k8s、
`kube-jupyterhub`、`jupyter-gpu`）。Phase 2 で `kube-sshuser` を `kube-tools` に rename し、
残り 3 つを `git subtree` で履歴ごと取り込んだ。

```
packages/kube_sshuser/src/kube_sshuser/
    cli.py                 サブコマンドの束ね役（唯一の entry point）
    common.py              run() / kubectl_get_json{,_or_raise}() / context / normalize_name / 時刻整形
    labels.py              ラベル・アノテーションのキーとセレクタ（Phase 1 で集約）
    provision_manifest.py  build_manifest(): f-string で複数ドキュメント YAML を組む
    provision_kubectl.py   apply と NodePort 割り当て、稼働状態の観測
    provision_user.py / modify_user.py / delete_user.py / status.py / doctor.py / terminate_pod.py
    registry.py            台帳（output/_registry）の読み書き

packages/kube_lab/src/kube_lab/
    lab_cli.py             argparse と main()。エントリは kube-lab と gpu-dev の 2 つ
    lab_core.py            再エクスポートのハブ（他モジュールはここ越しに読む）
    lab_defaults.py        PVC 名 / GPU / CPU / MEM / TTL の既定値
    lab_identity.py        sanitize_k8s_name / build_owner / build_pod_name
    lab_k8s.py             kubectl 実行、port-forward、can-i
    lab_listing.py         status の表組み
    lab_pod.py             build_pod_manifest() と ensure_pod()
    naming.py              PROG / TAG（起動名の追随）と改名通知

packages/kube_jupyterhub/kube_jupyterhub/cli.py   1 ファイル。Helm と kubectl を呼ぶだけ

images/ssh/                SSH コンテナイメージ（Dockerfile + entrypoint.sh）
images/jupyter/            Jupyter イメージ（独自 Makefile をルートから委譲）
docs/RUNBOOK.md            管理者向け運用手順書
docs/user/kube-lab.md      学生向け kube-lab の使い方（旧 docker-ssh の README）
skills/kube/               Claude Code 用 Skill（references/runbook.md は docs/RUNBOOK.md への symlink）
```

**各パッケージ / イメージに CLAUDE.md がある。**作業対象が決まったらそちらを読む。
この文書はパッケージ間の関係だけを扱い、個々の作り込みには立ち入らない。

**`packages/kube_lab` が SSH イメージに焼き込まれる**のがモノレポ化の決め手。Dockerfile の
`COPY packages/ /build/packages/` 1 行で済み、RBAC と kube-lab の同時変更が 1 つの diff に入る。

**旧リポジトリ名との対応**（外部の issue や古い URL を扱うとき用）:
`admin-tool` → `packages/kube_sshuser`、`docker-ssh` → `packages/kube_lab` + `images/ssh`、
`jupyter-gpu` → `images/jupyter`。GitHub の rename リダイレクトにより
`git+https://github.com/hiroshima-aidi/kube-sshuser.git` も当面は解決するが、
**`#subdirectory=packages/kube_sshuser` が無いとインストールは失敗する**。

## 全体の流れ（どのパッケージが何をするか）

```
[管理者] kube-sshuser create taro ...        ← packages/kube_sshuser
             ↓ 作るのは「入れ物」まで
         namespace ns-taro / PVC workspace / ResourceQuota / SA+RBAC / SSH Pod (NodePort 31000-31999)
             ↓
[利用者] ssh -p 31007 taro@<host>            ← SSH イメージは images/ssh 製
             ↓ SSH コンテナ内で
         kube-lab up --gpu 1                  ← PVC を /workspace にマウントした GPU Pod

[別系統] kube-jupyterhub apply / refresh / list / pvc
         images/jupyter（Jupyter イメージのビルド）
```

**JupyterHub 系（`kube_jupyterhub` / `images/jupyter`）と SSH 系（`kube_sshuser` / `kube_lab`）は別系統。**
同じクラスタ・同じユーザ台帳を共有しているかは未確認。片方の変更をもう片方に波及させないこと。

## 入口コマンド

詳細は各 `CLAUDE.md`。ここは「どこで何を打つか」の索引。**すべてリポジトリルートから。**

```bash
# Python パッケージ（全部 editable で入れる）
make dev-install

kube-sshuser <create|modify|delete|show|list|status|terminate|doctor> ...
kube-jupyterhub <apply|refresh|refresh-full|list|pvc> [--context ...] [--dry-run]

# SSH イメージ（ビルドコンテキストはリポジトリルート）
make ssh-build IMAGE=docker-ssh:latest
make ssh-push GITHUB_USER=... GITHUB_TOKEN=...   # ghcr.io へ（.env でも可）
make ssh-build-import                            # ビルド + k3s の containerd へ import

# Jupyter イメージ（images/jupyter/Makefile へ委譲。jupyter- を前に付ける）
make jupyter-build STACK=cpu WITH_IJULIA=1       # cpu | cuda12.2 | cuda11.8
make jupyter-push STACK=cuda12.2 IMAGE_TAG=2026.04.01
make jupyter-push-all
make jupyter-help                                # Jupyter 側の全ターゲットと変数
```

**Jupyter だけ委譲なのは意図的。** あの Dockerfile 群は `requirements/` と `scripts/` を
ビルドコンテキスト相対で `COPY` するので、コンテキストは `images/jupyter` のままにする必要がある。
`$(MAKE) -C images/jupyter` なら発行されるコマンドが単独リポジトリ時代と完全に一致する。

**テストファイルは 0 件**（`images/jupyter/scripts/smoke_test.sh` のみ）。
`kube_jupyterhub` は dev extras に pytest を宣言しているがテストは無く、`tests/` も無い。
lint / CI の設定も `kube_jupyterhub/pyproject.toml` の black・isort・mypy だけで、
ルートには何も無い（Phase 5 で揃える）。

**当面の検証は「挙動が変わらないことの証明」で回している**（テストが無いので）:

```bash
# マニフェストのゴールデン: リファクタの前後でバイト一致することを見る
#   kube_sshuser  build_manifest()      … 6 ケース
#   kube_lab      build_pod_manifest()  … 6 ケース
# CLI の --help を全サブコマンドで比較（COLUMNS を固定しないと折り返しで差が出る）
COLUMNS=100 PYTHONPATH=packages/kube_sshuser/src python3 -m kube_sshuser.cli --help

# イメージの中身の比較（Phase 2 で使った判定）
docker run --rm <img> find /opt/venv/lib -name '*.py' | sort
docker run --rm <img> kube-lab --help
```

**リポジトリ直下の `.venv/` は壊れた残骸。** `/Users/okamu/Documents/admin-tool/src` という
今は存在しないパスを指す editable インストールが入っている（モノレポ化前の遺物）。
gitignore されているので害は無いが、**これを activate すると動かない `kube-sshuser` を掴む。**
`make dev-install` で新しく作ること。

## パッケージをまたぐ結合点（変更時に必ず両方を見る）

- **RBAC と `kube-lab` は密結合。** `kube_sshuser/provision_manifest.py:120-147` の Role（`rules:` は 127 行目から） を、SSH コンテナ内の
  `kube-lab` が ServiceAccount で使う。突き合わせ済みの結果:
  **`pods/log` / `persistentvolumeclaims` / `events` は kube-lab が一度も使っていない過剰付与**、
  逆に `auth can-i`（`kube_lab` の `lab_k8s.py:103`）が要る `selfsubjectaccessreviews` は Role に無い。
- **PVC は SSH Pod にマウントされない（意図的）。** RWO の multi-attach を避けるため。
  マウントするのは `kube-lab up` が起こす GPU Pod 側（`kube_lab` の `lab_pod.py` が `claimName` を指定）。
- **PVC 名 `workspace` が両側の暗黙の契約。** admin 側 3 箇所（`provision_user.py:74`,
  `doctor.py:115`, `modify_user.py:163`）と `kube_lab` の `lab_defaults.py:5` に**独立したリテラル**として
  あり、`--pvc-name` を既定から変えて払い出すと kube-lab が黙って壊れる。
- **名前正規化が 3 実装で、規則が実際に食い違う。** 同じ入力を通して確認済み:

  | 入力 | `common.normalize_name()` | `sanitize_k8s_name()` | `entrypoint.sh` |
  |---|---|---|---|
  | `山田` / `é` | ValueError | **そのまま通過**（不正な k8s 名） | `''`（無言で空） |
  | `___` | ValueError | `user` | `''` |
  | 70 文字 | **63 に切り詰め** | 切り詰めなし | 切り詰めなし |

  `sanitize_k8s_name()` が `ch.isalnum()` を使う（`kube_lab` の `lab_identity.py:11`）ため非 ASCII が
  素通りする。その値はラベル値 `logical-name` にも入るので **`kube-lab up --name テスト` は
  apply が失敗する**。63 文字の差は、長いユーザ名で admin と kube-lab の namespace がずれる。
- **kubectl ラッパがまだ 3 実装。** `common.run()`（`common.py:95`）、`lab_k8s.run()`
  （`lab_k8s.py:7`）、`kube_jupyterhub` の `run()`（`cli.py:45`）。Phase 1 で
  `status.py` / `terminate_pod.py` のローカル版は消え、`common` は用途で 2 本に分かれた
  （`kubectl_get_json()` は失敗時 `None`、`kubectl_get_json_or_raise()` は `KubectlError`）。
  **統合先は Phase 3 の `kubelab_core.process`。**
- **`kube_lab` には素の `subprocess` が 7 箇所残る**（`lab_k8s.py:9,13,25,35,103,154`,
  `lab_listing.py:134`）。**このうち `run()` を通らないものはログを一切出さない** ので、
  学生が「何が起きたか分からない」状態になる。Phase 3 でここを潰す。
- **`--context` は `kube_lab` にだけ無い。** Phase 1 で `kube_jupyterhub` に入り、
  `kube_sshuser` には元からある。ただし SSH コンテナ内は単一クラスタなので優先度は低い。
- **イメージの受け渡し。** `kube-sshuser create --image` に渡すのが `images/ssh` がビルド・push するイメージ
  （`ghcr.io/hiroshima-aidi/ssh-for-k8s`）。
- **ドキュメントの同期は手動。** `docs/RUNBOOK.md` §1 の `kube-lab` の説明は
  `docs/user/kube-lab.md`（旧 docker-ssh README）から書き写したもの。追随させる仕組みは無い。
  **モノレポになったので、今は同じ diff で直せる。**
- **`kube-lab` は sudo ではなく通常ユーザで実行する**（決着済み）。owner を `$USER` から取り、
  kubeconfig が SSH ユーザの `$HOME` にあるため、sudo だと両方外れる。`docs/user/kube-lab.md` の図を直し、`warn_if_root()` を追加済み。

## 統合リファクタリング（進行中）

**承認済みの計画**: `~/.claude/plans/playful-enchanting-prism.md`。着手前に必ず読むこと。

**進捗（2026-08-28 時点）: Phase 0 / 1 / 2 / 2.5 完了。次は Phase 3。**

| Phase | 内容 | 状態 |
|---|---|---|
| 0 | 前始末、クラスタのスナップショット、sudo 矛盾の決着 | ✅ 完了 |
| 1 | Makefile 残骸削除、jupyterhub に `--context`/`--dry-run`/typed confirm、ラベル定数化 | ✅ 完了 |
| 2 | rename + subtree でモノレポ化、install URL 更新 | ✅ 完了 |
| 2.5 | `gpu-dev` → `kube-lab` 改名（旧名は 1 学期並走） | ✅ 完了 |
| 3 | 共通コア `kubelab_core` の抽出、名前正規化 3→1 | ⏭ **次はここ**。実クラスタ検証が要る |
| 4 | RBAC 契約の単一定義、過剰付与の削除、`kube-lab doctor` | 未着手 |
| 5 | CI・lint・setuptools_scm・イメージタグ統一 | 未着手 |
| 6+ | ラベル置換 / 台帳・PVC 統合 | **保留**（破壊的） |

方針は **モノレポ化 + 共通コア `kubelab_core` の切り出し**を Phase 0〜6 で段階実行。
決め手は、`kube-lab` が SSH イメージに焼き込まれる点 — 別リポジトリのままだと Dockerfile が
「GitHub から pip install」か vendoring になり、ビルドの再現性と RBAC の同時変更レビューが
両方壊れる。同一リポジトリなら `COPY packages/ /build/packages/` の 1 行で済む。

決定事項:

- **リポジトリは `hiroshima-aidi/kube-sshuser` を rename して `kube-tools`**（新規作成しない。
  GitHub の rename リダイレクトで既存の pip URL が生きる）
- **学生向け CLI `gpu-dev` は `kube-lab` に改名**（Phase 2.5 で実施済み。旧名をエイリアスで 1 学期並走）
- **リポジトリ名と CLI 名は分ける** — 両方 `kube-lab` だと repo と CLI が区別できない
- `jupyter-gpu`（remote が `rellab`）も取り込む
- RBAC の過剰付与（`pods/log` / `pvc` / `events`）は削る

後回しにするもの（いずれも破壊的）: 台帳と PVC の一本化（NFS 導入と合わせて設計）、
ラベルドメイン `provision-user.openai.local` の置換（稼働中リソースが持っており、
`status` / `doctor` / `delete-user` のセレクタが依存している）。

---

## セッションログ

### 2026-08-26

**やったこと**

- 4 リポジトリすべてに CLAUDE.md を整備し、このワークスペース CLAUDE.md を新設
- 統合の是非を調査。名前正規化 3 実装の食い違い、kubectl ラッパ 6 実装、RBAC の過不足、
  PVC 名の暗黙の契約を実コードで確認（結果は上記「結合点」に反映）
- 統合計画を策定・承認（`~/.claude/plans/playful-enchanting-prism.md`）
- **Phase 0（前始末）を実行**:
  - `jupyter-gpu`: `IMAGE_TAG` を `2026.04.01` に統一、`.DS_Store` を gitignore
  - `admin-tool`: `harden-and-skill` を **ff マージで main へ**（v0.5.0 + doctor + RUNBOOK
    + Skill）、README に「実クラスタ未検証」の注記。**タグは打っていない**
  - `docker-ssh`: **sudo の矛盾を決着** — README の図から sudo を削り、`warn_if_root()` を追加
  - 4 リポジトリすべて main・クリーン・push 済み

**保留中のタスク**

（Phase 0-4 のスナップショットは 2026-08-27 に取得済み。下記セッションログ参照）

**次のセッションへの申し送り**

- **Phase 1（無害な規約統一）はクラスタ不要**なので、スナップショットを待たずに着手できる。
  内容: docker-ssh の Makefile 残骸削除、kube-jupyterhub に `--context` / `--dry-run` /
  typed confirm を追加、admin-tool のローカル kubectl ラッパを `common` に寄せる、ラベル定数化
- Phase 1 の合否判定は **`build_manifest()` の出力が前後で完全一致すること**（挙動を変えない）
- `admin-tool` の `harden-and-skill` ブランチはマージ済みだがローカルに残っている。削除可

### 2026-08-27

**Phase 0-4（クラスタのスナップショット）完了。** `snapshot-2026-08-27/` に保存。

アクセス経路: `ssh -i ~/Dropbox/utilities/REL2.pem reladmin@clarinet.rel.hiroshima-u.ac.jp`
（このマシンから鍵認証で入れる。kubectl は reladmin の `~/.kube` で設定済み）

分かったこと:

- クラスタは **k3s v1.34.6、3 ノード**: `clarinet`(control-plane) / `flute` / `triangle`
- **SSH 系の実ユーザは `ns-okamumu` の 1 人だけ。** namespace 名の最大長は **10 文字**
  → **Phase 3 の名前正規化統一（63 文字切り詰め）は完全に無害**と確定
- `ns-okamumu`: SSH Pod 1（`ghcr.io/hiroshima-aidi/ssh-for-k8s:latest`、NodePort **31000**、
  131 日稼働）/ PVC `workspace` 100Gi / SA `ssh-user` + `ssh-user-role` + binding /
  ResourceQuota `quota`（GPU 2、cpu 16、mem 64Gi）
- **`gpu-dev` の Pod は現在 0 件**（`-l app=gpu-dev` で No resources found）
  → Phase 2.5 の `kube-lab` 改名時に生きた Pod を壊す心配は無い
- **ResourceQuota の `requests.storage` が 100Gi/100Gi で使い切り。** PVC を追加払い出すと
  即失敗する。クォータ既定値の見直しが要る（新規論点）
- ラベルドメイン `provision-user.openai.local/user` は Service / Deployment の
  **selector に入っている**（＝置換は Deployment 再作成が必須）。CLAUDE.md の既存の
  「後回し」判断はそのまま妥当
- 台帳は **ログインノードの `~/output/_registry`**（`KUBE_SSHUSER_OUT_DIR` は未設定で既定値）。
  `users/` に `okamumu` / `taro` / `taro2`（後 2 者はテスト残骸）。`output-backup/` に退避済み
- **ログインノードに `kube-sshuser` は入っていない**（`which` が空）。運用は手書きの
  `~/apply.sh` / `~/refresh-user.sh` / `~/refresh-user-full.sh` + `~/output/okamumu/provision-okamumu.yaml`。
  README の「実クラスタ未検証」は文字通りで、**CLI は本番で一度も使われていない**
- JupyterHub 系は別 namespace `jupyterhub` に PVC 8 件（claim-* 各 10Gi）+ hub-db-dir で稼働中

**次にやること**

- **Phase 1（無害な規約統一）に着手可**（クラスタ不要。合否は `build_manifest()` の出力一致）
- 新規論点: ResourceQuota の `requests.storage` 使い切り、台帳のテストユーザ `taro` / `taro2` の掃除、
  ログインノードの手書きスクリプトと `kube-sshuser` の実際の差分の突き合わせ

### 2026-08-27（続き）

**Phase 1（無害な規約統一）完了。3 リポジトリとも main・クリーン・push 済み。**

| リポジトリ | コミット | 内容 |
|---|---|---|
| `docker-ssh` | `e2d2468` | Makefile の残骸削除（`ADMIN_DIR` / `VENV` / `venv` / `admin-install` / `clean-venv`） |
| `kube-jupyterhub` | `86f84d3` | `--context` / `--dry-run` / `refresh-full` の typed confirm、実行経路を `run()` に一本化 |
| `admin-tool` | `f04609e` | ラベル定数を `labels.py` に集約、`kubectl_get_json` の重複解消 |

**合否判定はすべてクリア:**

- `build_manifest()` の出力が 6 ケースで**バイト単位一致**（ラベル定数化の前後）
- `kube-sshuser` の `--help` が全サブコマンドで**完全一致**
- `make -n` の出力が ssh-build / ssh-buildx / ssh-push / ssh-import / ssh-build-import / clean で**完全一致**
- `kube-jupyterhub --help` の差分は**追加した 2 フラグのみ**

**計画からの変更点（1 件）**

- 計画は「admin-tool のローカル kubectl ラッパを `common` に寄せると**初めて `--context` が効く**ので
  Phase 3 の実クラスタ検証項目に入れる」としていたが、**これは誤り**。ローカル版も `common.run()` を
  呼んでおり、`--context` は既に効いていた。実際の差は**失敗時の挙動だけ**（ローカル＝`RuntimeError`、
  common＝`None`）。そこで単純な統合ではなく、用途で 2 本に分けた:
  `kubectl_get_json()`（失敗時 None、存在確認用）と `kubectl_get_json_or_raise()`（失敗時 `KubectlError`）。
  **Phase 3 の実クラスタ検証項目からこの 1 件は落として良い。**

**挙動が変わったもの（意図的、3 件）**

1. `kube-jupyterhub refresh-full` の中止が exit 0 → **exit 1**（スクリプトから中止と完了を区別できる）
2. `kube-jupyterhub` のログ prefix が `[CMD]`(stdout) → `[cmd]`(stderr)、`prepull_images()` の
   DaemonSet apply も `run()` 経由になり `--context` / `--dry-run` が効くようになった
3. `status` / `terminate-pod` の kubectl 失敗が traceback → `KubectlError` 経由の短いエラーと正しい終了コード

**確認して変えなかったもの**

- `terminate --all` が SSH Pod も消す件は**意図的**。help も「delete all pods in the namespace」で、
  SSH Pod は Deployment 配下なので自動で作り直される。削除前に対象 Pod 一覧を JSON で出してから
  確認プロンプトなので、`ssh-<user>` が並ぶことは実行者に見えている。学生の SSH セッションは切れる。

**次にやること**

- **Phase 2（モノレポ統合）**。クラスタ不要。`kube-sshuser` を GitHub 上で `kube-tools` に rename し、
  `git subtree add` で 3 つを履歴ごと取り込む。**rename は GitHub 側の操作なのでユーザの作業が要る。**
- `admin-tool` の `harden-and-skill` ブランチはマージ済み。ローカルに残っているので削除可

### 2026-08-27（Phase 2）

**Phase 2（モノレポ統合）完了。** `kube-sshuser` を GitHub 上で `kube-tools` に rename
（ユーザ実施）、残り 3 リポジトリを `git subtree add` で履歴ごと取り込み、最終レイアウトへ移動した。
**66 ファイルすべて git が rename として検出**（＝内容は動いていない）。

**合否判定（Phase 2 はクラスタ不要、すべてクリア）:**

- SSH イメージの新旧比較: `find /opt/venv/lib -name '*.py'` が **749 ファイルで完全一致**
- `gpu-dev --help` が新旧イメージで**バイト一致**（`up` / `down` / `status` 含む）
- `/entrypoint.sh` の md5 が新旧イメージで一致
- `kube-sshuser --help` / `kube-jupyterhub --help` が全サブコマンドで**バイト一致**
- `make -n ssh-*` の発行コマンドが Dockerfile パス以外**完全一致**
- `make -n jupyter-build` が単独リポジトリ時代と**同一のコマンド・同一のイメージタグ**

**設計判断（計画から具体化した点）**

- **Jupyter の Makefile は統合せず `$(MAKE) -C images/jupyter` に委譲した。** あの Dockerfile 群は
  `requirements/` と `scripts/` をビルドコンテキスト相対で `COPY` するので、コンテキストを
  `images/jupyter` に保つ必要がある。委譲なら 257 行を書き換えずに発行コマンドが完全一致する。
  ルートからは `make jupyter-<target>` で届く（`jupyter-%` パターンルール）。
- **Dockerfile の wheel ビルドを `--outdir /build/dist packages/kube_lab` に変更。**
  `COPY packages/ /build/packages/` としたので、Phase 3 で `kubelab_core` を同じ venv に
  入れるときは `-m build` を 1 行足すだけで済む。
- **`docs/RUNBOOK.md` と `skills/` の相対関係は動かしていない。**
  `skills/kube/references/runbook.md -> ../../../docs/RUNBOOK.md` は解決を確認済み。
  `scripts/install-skill.sh` もリポジトリルート相対なのでそのまま動く。

**壊してはいけないものの扱い**

- `pip install git+.../kube-sshuser` → **`git+https://github.com/hiroshima-aidi/kube-tools.git#subdirectory=packages/kube_sshuser`**
  に更新（RUNBOOK §0.1 / 両 README を同時に）。互換 shim のルート pyproject は置いていない。
  **旧 URL は GitHub のリダイレクトで解決するが `#subdirectory=` が無いと失敗する**ので、
  古い手順書を見ている人には新 URL を案内すること。
- `output/_registry` は `.gitignore` 済みで移動対象外。クラスタ操作は一切していない。
- イメージ名 `ghcr.io/hiroshima-aidi/ssh-for-k8s` / `ghcr.io/rellab/jupyter-gpu` は不変。

**次にやること**

- **Phase 2.5（`gpu-dev` → `kube-lab` 改名）**。クラスタ不要。`packages/kube_lab` の中身は
  まだ `src/ssh_tool/` のままなので、モジュール名・配布名・`gpu_dev*.py` のリネームと
  エイリアス並走をここで入れる。
- ワークスペース `~/Documents/kube` にはまだ旧 4 ディレクトリが残っている。
  `admin-tool/` が新しい `kube-tools` リポジトリ本体。他 3 つは統合済みなので整理して良い。

### 2026-08-27（Phase 2.5）

**Phase 2.5（`gpu-dev` → `kube-lab` 改名）完了。** クラスタ操作なし。

- モジュール `ssh_tool` → `kube_lab`、ファイル `gpu_dev*.py` → `lab_*.py`、
  配布名 `ssh-tool` → `kube-lab`（v0.3.0）
- `[project.scripts]` に **`kube-lab` と `gpu-dev` の両方**を同じ `main()` で登録。
  `gpu-dev` で起動したときだけ stderr に改名を知らせる 1 行が出る。**1 学期並走後に削除。**
- 新設 `naming.py` が `PROG` / `TAG` を持ち、**メッセージ prefix と提案コマンドが起動名に追随**する。
  `gpu-dev` で起動した人に `kube-lab down` を勧めると手元のメモに無いコマンドを案内することになるため。

**合否判定（すべてクリア）:**

- `build_pod_manifest()` の出力が 6 ケースで**バイト一致**（ラベルを触っていないので当然そうなるべき）
- イメージ内で `kube-lab --help` と `gpu-dev --help` が**一致**（差は usage 行の prog 名と、
  prog が 1 文字短いことによる argparse の折り返しインデントのみ）
- `gpu-dev` 起動時のみ改名通知が出て、`kube-lab` では出ないことを実イメージで確認

**変えていないもの（意図的）**

- **ラベル `app: gpu-dev` / アノテーション `gpu-dev/*`。** 稼働中の Pod が持っており、
  `down --all` と `status` のセレクタ（`lab_k8s.py:80`, `lab_listing.py:142`）が依存している。Phase 6。
- **`--help` の「gpu-dev pod」という語。** Pod のラベルが実際に `app=gpu-dev` である以上、
  ここを `kube-lab pod` にすると `kubectl get pods -l ...` を打つ人に嘘を教えることになる。
  ラベル移行（Phase 6）と同時に直す。

**ついでに直したもの**

- `packages/kube_lab/src/ssh_tool/__pycache__/*.pyc` が**追跡されたまま**だった
  （旧 ssh-for-k8s の `.gitignore` に `__pycache__` が無く、Phase 2 でそのまま持ち込んでいた）。
  `git rm --cached` で外した。ルートの `.gitignore` には元から入っている。

**次にやること**

- **Phase 3（共通コア `kubelab_core` の抽出）**。ここから**実クラスタ検証が要る**。
  Phase 0-4 の実測（既存 namespace 名の最大長 10 文字）より、名前正規化の統一は無害と確定済み。
  Phase 1 の訂正により、`kubectl_get_json` の `--context` に関する検証項目は不要。

### 2026-08-28

**やったこと**

- CLAUDE.md を実際の現状に合わせて更新（構成・コマンド・進捗表）。以下の古い記述を訂正:
  - 「kubectl ラッパ 6 実装」→ Phase 1 で 2 つ消えて**現在 3 実装**
  - `modify_user.py:164` → `:163`、Role は `provision_manifest.py:120-147`、
    `auth can-i` は `lab_k8s.py:103`
  - `kube_lab` に残る素の `subprocess` を**7 箇所**と特定
    （`lab_k8s.py:9,13,25,35,103,154`, `lab_listing.py:134`）
- **Phase 3 の下調べ**（コード変更はまだ無し）。読んだのは `common.py` 全体、
  `lab_defaults.py` / `lab_identity.py` / `lab_k8s.py` / `lab_listing.py`、
  `entrypoint.sh` の `normalize_namespace()`

**見つけたこと**

- **リポジトリ直下の `.venv/` が壊れている。** `/Users/okamu/Documents/admin-tool/src` という
  モノレポ化前のパスを指す editable インストール。gitignore 済みで害は無いが、
  activate すると動かない `kube-sshuser` を掴む。`make dev-install` を使うこと。
- **`kube_lab` の素の `subprocess` は「ログを出さない」ことが実害。** `run()` を通る 1 箇所だけが
  `[cmd] ...` を出し、残り 6 箇所は無言。学生が失敗したときに何が起きたか分からない。
  Phase 3 の `kubelab_core.process` への統合はここが本命。

**Phase 3 の作業単位（計画どおり、1 パッケージ 1 コミット）**

1. `kubelab_core` を作り、`kube_sshuser/common.py` は再エクスポートだけ残す（既存 import を壊さない）
2. `kube_lab` を切り替え。素の `subprocess` 7 箇所を `run()` に通す。`lab_core.py` のハブは残す
3. **`entrypoint.sh` の `normalize_namespace()` を削除し `kubelab-name` CLI に委譲**
   （`[project.scripts] kubelab-name = "kubelab_core.names:main"`、Dockerfile の builder で
   core の wheel も同じ venv に入れる）。**sh/Python の 2 実装が消える、モノレポでなければ書けない部分**
4. `kube_jupyterhub` を切り替え

**次のセッションへの申し送り**

- **名前正規化の統一は無害と確定済み。** Phase 0-4 の実測で既存 namespace は `ns-okamumu` の
  1 つだけ、**最大長 10 文字**（63 文字の切り詰め規則の差に当たる人が居ない）。
  それでも `tests/test_names_backcompat.py` に既存名を埋めて固定すること（これが最初のテストになる）。
- **Phase 3 は実クラスタ検証が要る**が、`kube-lab` の Pod は現在 0 件・稼働ユーザ 1 人なので
  テスト用の新規ユーザを 1 つ払い出して SSH → `kube-lab up --gpu 0` → `status` → `down` で足りる。
  **稼働中の `ns-okamumu` には触らない。**
- クラスタへは `ssh -i ~/Dropbox/utilities/REL2.pem reladmin@clarinet.rel.hiroshima-u.ac.jp`。
  kubectl が使えるのは clarinet のみ（flute / triangle は worker で kubeconfig が無い）。
- ワークスペース `~/Documents/kube` に残る `docker-ssh/` `kube-jupyterhub/` `jupyter-gpu/` は
  **取り込み済みの旧ディレクトリ。編集しても kube-tools に反映されない。**削除の判断はユーザ待ち。
