# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## このリポジトリの性質

`hiroshima-aidi/kube-tools` は、研究室の Kubernetes 運用ツールを 1 つにまとめた**モノレポ**。
以前は 4 つの独立したリポジトリだった（`admin-tool` = kube-sshuser、`docker-ssh` = ssh-for-k8s、
`kube-jupyterhub`、`jupyter-gpu`）。Phase 2 で `kube-sshuser` を `kube-tools` に rename し、
残り 3 つを `git subtree` で履歴ごと取り込んだ。

```
packages/kube_sshuser/     kube-sshuser CLI（管理者）
packages/kube_lab/         kube-lab CLI（学生）。旧名 gpu-dev は今学期のみ並走
packages/kube_jupyterhub/  kube-jupyterhub CLI（管理者・別系統）
images/ssh/                SSH コンテナイメージ（Dockerfile + entrypoint.sh）
images/jupyter/            Jupyter イメージ（独自 Makefile をルートから委譲）
docs/RUNBOOK.md            管理者向け運用手順書
docs/user/kube-lab.md      学生向け kube-lab の使い方（旧 docker-ssh の README）
skills/kube/               Claude Code 用 Skill
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
`kube_jupyterhub` は dev extras に pytest を宣言しているがテストは無い。

## パッケージをまたぐ結合点（変更時に必ず両方を見る）

- **RBAC と `kube-lab` は密結合。** `kube_sshuser/provision_manifest.py:117-135` の Role を、SSH コンテナ内の
  `kube-lab` が ServiceAccount で使う。突き合わせ済みの結果:
  **`pods/log` / `persistentvolumeclaims` / `events` は kube-lab が一度も使っていない過剰付与**、
  逆に `auth can-i`（`kube_lab` の `lab_k8s.py:100`）が要る `selfsubjectaccessreviews` は Role に無い。
- **PVC は SSH Pod にマウントされない（意図的）。** RWO の multi-attach を避けるため。
  マウントするのは `kube-lab up` が起こす GPU Pod 側（`kube_lab` の `lab_pod.py` が `claimName` を指定）。
- **PVC 名 `workspace` が両側の暗黙の契約。** admin 側 3 箇所（`provision_user.py:74`,
  `doctor.py:115`, `modify_user.py:164`）と `kube_lab` の `lab_defaults.py:5` に**独立したリテラル**として
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
- **kubectl ラッパが 6 実装 + 素の `subprocess.run` が 5 箇所。** `kubectl_get_json()` は同名で
  3 つあり、**`common.py:112` は失敗時 `None`、`status.py:25` は `RuntimeError` と挙動が逆**
  （`terminate_pod.py:20` はその丸写し）。`--context` は Phase 1 で `kube_jupyterhub` にも入り、残るは `kube_lab`。
- **イメージの受け渡し。** `kube-sshuser create --image` に渡すのが `images/ssh` がビルド・push するイメージ
  （`ghcr.io/hiroshima-aidi/ssh-for-k8s`）。
- **ドキュメントの同期は手動。** `docs/RUNBOOK.md` §1 の `kube-lab` の説明は
  `docs/user/kube-lab.md`（旧 docker-ssh README）から書き写したもの。追随させる仕組みは無い。
  **モノレポになったので、今は同じ diff で直せる。**
- **`kube-lab` は sudo ではなく通常ユーザで実行する**（決着済み）。owner を `$USER` から取り、
  kubeconfig が SSH ユーザの `$HOME` にあるため、sudo だと両方外れる。`docs/user/kube-lab.md` の図を直し、`warn_if_root()` を追加済み。

## 統合リファクタリング（進行中）

**承認済みの計画**: `~/.claude/plans/playful-enchanting-prism.md`。着手前に必ず読むこと。

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
