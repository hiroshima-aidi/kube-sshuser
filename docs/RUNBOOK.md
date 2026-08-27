# kube-sshuser 運用手順書

研究室クラスタで学生ごとの SSH 環境を払い出す管理者向けの手順書です。
コマンドの網羅的なリファレンスは [README.md](../README.md)、ここでは **やりたいこと単位** で手順をまとめます。

---

## この手順書の対象

**ここに書いてあるのは管理者の作業だけです。** kube-sshuser が作るのは「入れ物」まで
（namespace / PVC / クォータ / SSH の入口）で、その中で GPU Pod を動かすのは利用者側の
`kube-lab`（`packages/kube_lab`、旧名 `gpu-dev`）の担当です。

```
[管理者]  kube-sshuser create taro ...
              ↓ 作られるもの
          namespace ns-taro / PVC workspace / ResourceQuota / SSH Pod (NodePort)
              ↓
[利用者]  ssh -p 31007 taro@<host>
              ↓ SSH コンテナの中で
          kube-lab up --gpu 1       ← GPU Pod を起動（PVC を /workspace にマウント）
          kube-lab status / down
```

| やりたいこと | 担当 | 参照先 |
|---|---|---|
| 環境の払い出し・変更・削除、稼働状況の確認 | **kube-sshuser（この手順書）** | 以下 |
| GPU Pod の起動・停止、TTL や GPU 数の指定 | 利用者の `kube-lab` | `docs/user/kube-lab.md` |
| SSH コンテナイメージの更新 | docker-ssh | 同上 |
| JupyterLab / JupyterHub のデプロイ | **kube-jupyterhub（別ツール）** | kube-jupyterhub の README |
| Jupyter イメージのビルド | jupyter-gpu | jupyter-gpu の README |

学生から「GPU Pod が起動しない」「Jupyter が使いたい」と言われた場合、**多くは
kube-sshuser の問題ではありません。** ただしクォータ不足やノードラベルなど、
管理者側の設定が原因のこともあるので §7 で切り分けてください。

---

## 0. 事前準備（管理者マシンの初期設定）

### 0.1 インストール

```bash
sudo python3 -m venv /opt/venv
sudo /opt/venv/bin/pip install --upgrade pip
sudo /opt/venv/bin/pip install "git+https://github.com/hiroshima-aidi/kube-tools.git#subdirectory=packages/kube_sshuser"
export PATH="/opt/venv/bin:$PATH"
```

### 0.2 レジストリの場所を固定する（重要）

kube-sshuser はクラスタとは別に、ローカルに「誰にどの環境を払い出したか」の台帳
（レジストリ）を持ちます。既定値は `./output` という**相対パス**なので、実行した
ディレクトリが違うと台帳を見失います。

必ず環境変数で固定してください。

```bash
echo 'export KUBE_SSHUSER_OUT_DIR=/srv/kube-sshuser' >> ~/.bashrc
source ~/.bashrc
```

複数の管理者・複数の踏み台から操作するなら、**共有ストレージ上の同じパス**を指すこと。
台帳が分裂すると、既に使われている環境に再度 `create` してしまう事故につながります。

コマンド実行時、実際に使った台帳のパスが stderr に出ます。毎回ここを確認する習慣を。

```
[registry] /srv/kube-sshuser ($KUBE_SSHUSER_OUT_DIR)
```

### 0.3 接続先クラスタの確認

```bash
kubectl config current-context
```

破壊的な操作（create / delete / terminate）は実行前に context を表示して確認を求めますが、
複数クラスタを扱うなら `--context` で毎回明示するのが安全です。

### 0.4 動作確認

```bash
kube-sshuser list        # 台帳（クラスタは見ない）
kube-sshuser status      # クラスタ上の管理対象 namespace 一覧
```

---

## 1. 新しく学生に SSH 環境を払い出す

### 手順

**① 学生から公開鍵を受け取る**

`~/.ssh/id_ed25519.pub` の中身をもらいます。`ssh-ed25519 AAAA... name@host` の 1 行です。
**秘密鍵（`.pub` が付かないファイル）を送らせないよう注意してください。**

```bash
mkdir -p /srv/kube-sshuser/keys
vi /srv/kube-sshuser/keys/taro.pub   # 受け取った 1 行を貼る
```

**② 払い出しの内容を決める**

| 項目 | オプション | 既定値 | 目安 |
|---|---|---|---|
| 表示名 | `--name` | なし | 実名。後から `modify` で変更可 |
| 説明 | `--desc` | なし | 「M1 / 〇〇研究」など。棚卸しで効く |
| ストレージ | `--storage` | `100Gi` | `kube-lab` の Pod に `/workspace` としてマウントされる |
| GPU | `--gpu-quota` | `1` | 同時に確保できる GPU 数 |
| CPU | `--cpu-quota` | `16` | namespace 全体の上限 |
| メモリ | `--memory-quota` | `64Gi` | namespace 全体の上限 |

**③ 作成する**

```bash
kube-sshuser create taro \
  --name "山田 太郎" \
  --desc "M1 / CUDA 演習" \
  --public-key-file /srv/kube-sshuser/keys/taro.pub \
  --image ghcr.io/hiroshima-aidi/ssh-for-k8s:latest \
  --pull always \
  --storage 100Gi \
  --gpu-quota 1
```

実行すると context と対象 namespace が表示され、確認を求められます。
問題なければ `y`。処理は 3 段階で進みます。

```
[1/3] applying manifest (nodePort=31007, attempt 1/5)...
[2/3] waiting for ssh deployment rollout...
[3/3] collecting endpoint info...
```

最後に JSON サマリが出ます。`ssh_endpoint` が学生に伝える接続先です。

**④ 学生に接続情報と使い方を伝える**

```bash
kube-sshuser show taro
```

`SSH > Endpoint`（例 `10.0.0.12:31007`）を確認し、次を伝えます。

```
ssh -p 31007 taro@10.0.0.12
```

ログインユーザ名は kube-sshuser に渡したユーザ名と同じです。

ログイン後の GPU の使い方は `kube-lab` の担当です。あわせて伝えます。

```bash
kube-lab up --gpu 1       # GPU Pod を起動して入る
kube-lab status           # 自分の Pod 一覧
kube-lab down             # 片付け
```

- 作業データは `/workspace`（PVC）に置く。それ以外は Pod と一緒に消える
- 既定の TTL は 3600 秒。長く使うなら `--ttl` を指定する
- 詳細なオプションは `docs/user/kube-lab.md` を見るよう案内する

**このコマンドは `gpu-dev` から `kube-lab` に改名しました（2026-08-27、v0.3.0）。**
`gpu-dev` も**今学期いっぱいは同じように動きます**（実行すると改名を知らせる 1 行が出ます）。
学期末に `gpu-dev` を削除する予定なので、新しく案内するときは `kube-lab` を使ってください。
**Pod のラベル `app=gpu-dev` とアノテーション `gpu-dev/*` は変えていません** — 稼働中の Pod が
持っており、`down --all` のセレクタが依存しているためです（置換は Phase 6）。

### 注意点

- **NodePort は自動で 31000-31999 から選ばれます。** 番号を指定したい場合のみ `--port`。
  この範囲外を指定すると Kubernetes 側で弾かれます。
- **同じユーザ名で 2 回 `create` はできません。** 台帳が active なら中断します。
  さらに、台帳に無くてもクラスタ側に同名 namespace があれば中断します
  （他人の環境を上書きしないための保護）。意図的な上書きは `--force`。
- **PVC は SSH Pod にはマウントされません（意図的な設計です）。**
  RWO の multi-attach を避けるため、SSH コンテナは入口に徹しています。
  PVC は利用者が `kube-lab up` で起動する GPU Pod に `/workspace` として
  マウントされます。学生には次の 2 点を伝えてください。
  - 永続させたいデータは `/workspace` に置く
  - SSH コンテナ内のホームディレクトリは Pod の再作成で消える

---

## 2. 割り当てリソースを変更する

`modify` は **Pod を再起動せずに** 変更できる項目だけを扱います。

### GPU / CPU / メモリのクォータを変える

```bash
kube-sshuser modify taro --gpu-quota 2
kube-sshuser modify taro --cpu-quota 32 --memory-quota 128Gi
```

- 反映は即時です（ResourceQuota の patch）。
- **減らす場合は注意。** すでに使用中の量より小さい値にすると、超過状態になり
  新しい Pod が作れなくなります。事前に使用量を確認してください。

  ```bash
  kubectl -n ns-taro get resourcequota quota -o yaml
  ```

### ストレージを増やす

```bash
kube-sshuser modify taro --storage 200Gi
```

- **拡張のみ。縮小はできません**（Kubernetes の PVC の仕様）。
- StorageClass が `allowVolumeExpansion: true` である必要があります。

### 表示名・説明を直す

```bash
kube-sshuser modify taro --name "山田 太郎" --desc "M2 / 修論"
```

namespace と Deployment のアノテーションを書き換えます。`status` の一覧表示に反映されます。

### 変更できないもの

イメージ、公開鍵、NodePort、UID/GID は `modify` では変更できません（Pod の再作成が要るため）。
公開鍵については §6 を参照。

---

## 3. 稼働状況を確認する

### 全体を見る

```bash
kube-sshuser status
```

管理対象 namespace の一覧が出ます。AGE / PORT / PODS / CPU / MEM / GPU / STORAGE / 表示名 / 説明。
「誰がどれだけ使っているか」の把握はここから。

### 特定の学生の中を見る

```bash
kube-sshuser status ns-taro
```

その namespace の Pod 一覧（NAME / STATUS / AGE / NODE / GPU / CPU / MEM）。

### 台帳を見る

```bash
kube-sshuser list                  # 全件を status 別に
kube-sshuser list --status active  # 稼働中のみ
kube-sshuser show taro             # 1 人の詳細（鍵の fingerprint、要求値と実測値）
kube-sshuser show taro --json      # スクリプト向け
```

### 使い分け

| 知りたいこと | コマンド |
|---|---|
| 今クラスタで何が動いているか | `status` |
| 誰にいつ何を払い出したか | `list` / `show` |
| 過去の操作履歴（監査） | `cat $KUBE_SSHUSER_OUT_DIR/_registry/events.ndjson` |

`status`（クラスタ）と `list`（台帳）が食い違う場合は §7.4 を参照。

---

## 4. 暴走している Pod を止める

学生の学習ジョブが GPU を掴んだまま返さない、といったケース。

**① 対象を特定する**

```bash
kube-sshuser status ns-taro
```

**② 止める**

```bash
# 特定の Pod だけ
kube-sshuser terminate ns-taro train-job-xxxxx

# namespace 内の全 Pod
kube-sshuser terminate ns-taro --all
```

実行前に対象一覧と context が表示され、確認を求められます。

**③ 再作成される場合**

Deployment / Job / ReplicaSet 配下の Pod は削除しても再作成されます。
出力の `owners` に `Deployment/...` などが出ていたらこれに該当します。
本当に止めるには controller 側を操作してください。

```bash
kubectl -n ns-taro get deploy,job
kubectl -n ns-taro scale deploy/<name> --replicas=0
kubectl -n ns-taro delete job/<name>
```

**④ どうしても終了しない場合**

```bash
kube-sshuser terminate ns-taro <pod> --force
```

`--force` は grace period 0 の強制削除です。データ整合性を捨てる操作なので最後の手段に。

> SSH 用の Pod（`ssh-taro-...`）を消すと学生のセッションが切れますが、Deployment が
> すぐ再作成します。SSH 環境ごと止めたい場合は `kubectl -n ns-taro scale deploy/ssh-taro --replicas=0`。

---

## 5. 卒業・退室した学生の環境を削除する

### 事前確認

**削除は namespace ごと消すため、PVC のデータも失われます。復旧できません。**

```bash
kube-sshuser show taro          # 対象が合っているか
kube-sshuser status ns-taro     # 動いている Pod が無いか
```

必要なデータがあれば先に退避してください。

```bash
kubectl -n ns-taro cp <pod>:/home/taro/results ./taro-results
```

### 削除する

```bash
kube-sshuser delete taro
```

対象（context / namespace / 消える PVC / Pod 数）が表示された後、
**namespace 名の入力**を求められます。

```
This deletes namespace 'ns-taro' in context 'lab-cluster' including its
PersistentVolumeClaims. Stored data will be lost and cannot be recovered.
Type 'ns-taro' to confirm:
```

### バリエーション

```bash
# 生成した YAML や台帳は残したい
kube-sshuser delete taro --keep-files

# クラスタは触らず、ローカルの生成物だけ消す
kube-sshuser delete taro --keep-namespace

# 非対話（スクリプトから。確認を飛ばすので取り扱い注意）
kube-sshuser delete taro --yes
```

削除後も台帳のレコードは `status: deleted` として残ります（`list --status deleted`）。
監査ログ `events.ndjson` にも記録されます。

---

## 6. 学生が秘密鍵をなくした / 鍵を変えたい

**現状、公開鍵だけを差し替えるコマンドはありません。**
`delete` → `create` はデータ消失を伴うため、次の回避策を使ってください。

### 回避策：Deployment の環境変数を直接書き換える

```bash
# 新しい公開鍵を確認
cat /srv/kube-sshuser/keys/taro-new.pub

# Deployment の SSH_PUBLIC_KEY を差し替える（Pod が再作成されます）
kubectl -n ns-taro set env deploy/ssh-taro \
  SSH_PUBLIC_KEY="$(cat /srv/kube-sshuser/keys/taro-new.pub)"

kubectl -n ns-taro rollout status deploy/ssh-taro
```

**この方法では台帳の `ssh_key.fingerprint_sha256` が更新されません。**
誰の鍵が入っているか分からなくなるので、鍵を差し替えたら必ず記録を残してください
（`--desc` に日付を書く、別途メモを残すなど）。

```bash
kube-sshuser modify taro --desc "M1 / CUDA 演習 (鍵を 2026-08-26 に更新)"
```

---

## 7. トラブルシューティング

### 7.1 `create` が「namespace already exists」で止まる

```
error: namespace 'ns-taro' already exists in cluster 'lab-cluster' but is not
recorded as active in this registry (out-dir: ./output).
```

台帳とクラスタが食い違っています。まず**どちらが正しいか**を確認してください。

```bash
kubectl get namespace ns-taro -o yaml | head -30   # いつ誰の環境か
echo $KUBE_SSHUSER_OUT_DIR                          # 正しい台帳を見ているか
```

- **`--out-dir` が違っていた** → 正しいパスを指定し直す（§0.2）
- **本当に古い環境が残っている** → `kube-sshuser delete taro` してから作り直す
- **上書きして構わないと確信がある** → `--force` を付けて再実行

`--force` は既存の学生の公開鍵とクォータを上書きします。安易に使わないこと。

### 7.2 SSH Pod が Pending のまま起動しない

```bash
kubectl -n ns-taro describe pod <pod名> | tail -20
```

よくある原因:

| Events の内容 | 原因 | 対処 |
|---|---|---|
| `didn't match node selector` | ログインノードのラベルが無い | `kubectl label node <node> role=login-server` |
| `Insufficient nvidia.com/gpu` | GPU の空きが無い | 他の Pod の終了を待つ / `terminate` |
| `ImagePullBackOff` | イメージ名かレジストリ認証 | `--image` を確認、`--pull always` を再指定 |
| `exceeded quota` | クォータ超過 | `modify --cpu-quota` などで拡張 |

### 7.3 学生が「Pod が作れない」「kube-lab が失敗する」と言ってくる

まず **どちら側の問題か** を切り分けます。`kube-lab` 自体の使い方の問題なら `docs/user/kube-lab.md` の
担当ですが、次のエラーは管理者側（クォータ・ラベル）の問題です。

エラーが `must specify limits.cpu` / `must specify requests.memory` の場合、
ResourceQuota が limits/requests の明示を要求しているためです。
学生の manifest に次を書かせてください。

```yaml
resources:
  requests:
    cpu: "2"
    memory: 8Gi
    nvidia.com/gpu: 1
  limits:
    cpu: "2"
    memory: 8Gi
    nvidia.com/gpu: 1
```

`exceeded quota` の場合は割り当て超過です。使用状況を確認してから判断してください。

```bash
kubectl -n ns-taro get resourcequota quota -o yaml
```

### 7.4 `list` に居るのに `status` に出てこない

台帳（ローカル）とクラスタが乖離しています。手で namespace を消した場合などに起きます。

```bash
kubectl get namespace ns-taro          # 実在するか
kube-sshuser show taro                 # 台帳上の状態
```

クラスタに無いのが正しければ、台帳を実態に合わせます。

```bash
kube-sshuser delete taro --keep-namespace   # レコードを deleted にし、生成物を消す
```

### 7.5 別のクラスタを操作してしまいそうになった

`create` / `delete` / `terminate` は確認プロンプトに context 名を出します。
出力の `"context": "..."` が想定と違ったら **必ず中断**してください。

```bash
kubectl config get-contexts               # 一覧
kube-sshuser status --context lab-cluster # 明示指定
```

### 7.6 NodePort が枯渇した

```
error: failed to allocate a free NodePort after 5 attempts
```

31000-31999 が埋まっています。使われていない古い環境が無いか確認してください。

```bash
kube-sshuser list --status active
kubectl get svc -A -o wide | sort -k5
```

### 7.7 kubectl のエラーがそのまま出てきた

```
error: command failed (exit 1): kubectl ... : <kubectl のメッセージ>
```

kube-sshuser ではなく Kubernetes 側の拒否です。メッセージ本文（権限、リソース不足、
バリデーション）を読んで対処してください。

---

## 7.8 台帳とクラスタを一括で突き合わせる

個別の切り分けの前に、まず全体の食い違いを見ます。

```bash
kube-sshuser doctor
```

| VERDICT | 意味 | 対処 |
|---|---|---|
| `missing-in-cluster` | 台帳は active だが namespace が無い | 手で消された。§7.4 |
| `orphan-namespace` | 台帳は deleted だが namespace が残っている | 削除が途中で失敗した。`delete` をやり直す |
| `untracked-namespace` | 管理対象 namespace だが台帳に記録が無い | `--out-dir` が違う可能性。§0.2 を確認 |
| `drift` | クォータや PVC が払い出し時と違う | 手で `kubectl patch` した。意図的なら `modify` で台帳を揃える |
| `ok` | 一致 | — |

問題があると終了コード 1 を返すので、定期チェックをスクリプト化できます。

---

## 8. 定期作業

### 学期はじめ

- 新入生の環境を払い出す（§1）
- `--desc` に学年と所属を必ず入れる（棚卸しが楽になる）

### 月次の棚卸し

```bash
kube-sshuser doctor                       # 台帳とクラスタの食い違い
kube-sshuser status                       # 全体のリソース配分
kube-sshuser list --status active         # 台帳上の稼働中
```

- 長期間 Pod が 0 のままの環境 → 本人に確認
- GPU を占有し続けている環境 → §4
- 台帳とクラスタの食い違い → §7.4

### 年度末

- 卒業生の環境を削除（§5）。データ退避の要否を必ず本人に確認する
- 削除記録の確認

  ```bash
  grep delete_completed $KUBE_SSHUSER_OUT_DIR/_registry/events.ndjson | tail -20
  ```

### 台帳のバックアップ

レジストリは復旧不能な運用記録です。定期的にバックアップしてください。

```bash
tar czf ~/kube-sshuser-registry-$(date +%Y%m%d).tar.gz \
  -C /srv/kube-sshuser _registry
```

---

---

## 9. Claude Code から使う

管理作業は年に数回しかないため、手順を覚えていなくても済むように
Claude Code 用の Skill を同梱しています。

### 導入（ログインノードで一度だけ）

```bash
cd <このリポジトリ>
./scripts/install-skill.sh
```

`~/.claude/skills/kube` がリポジトリ内の `skills/kube` への symlink になります。
`git pull` すると CLI・手順書・Skill が同時に更新されます。

### 使い方

Claude Code のセッションで `/kube` と打つか、単に用件を書きます。

```
/kube 新入生の田中さんに環境を作りたい
今 GPU を使ってるのは誰？
卒業した taro の環境を消して
```

Skill は作業前に必ず kube-context と現状を提示し、削除の際は
**消えるものを提示して確認を取ってから**実行します。

### 前提と注意

- `kube-sshuser` は **単体の CLI として今までどおり使えます。** Skill は
  「手順書を読んでコマンドを打つ」役を Claude が担うだけで、CLI 側には何も変更がありません。
  Claude が打ったコマンドは `[cmd] ...` として出るので、後から手で再現できます
- 参照系（`status` / `list` / `show` / `doctor` / `kubectl get`）は
  `.claude/settings.json` で事前許可されており、確認プロンプトなしで流れます
- **変更系（`create` / `modify` / `delete` / `terminate`）は毎回プロンプトが出ます。**
  内容を確認してから承認してください
- Claude が `--force` を提案してきたら、理由を確認してください。既存の学生環境を
  上書きする操作です（§7.1）

---

## 付録: よく使うコマンド早見表

```bash
# 払い出し
kube-sshuser create <user> --name "<氏名>" --desc "<所属>" \
  --public-key-file <鍵> --image <イメージ> --storage 100Gi --gpu-quota 1

# 接続先の確認
kube-sshuser show <user>

# 稼働状況
kube-sshuser status
kube-sshuser status ns-<user>

# リソース変更
kube-sshuser modify <user> --gpu-quota 2 --memory-quota 128Gi
kube-sshuser modify <user> --storage 200Gi

# Pod を止める
kube-sshuser terminate ns-<user> <pod>
kube-sshuser terminate ns-<user> --all

# 削除
kube-sshuser delete <user>

# 台帳
kube-sshuser doctor
kube-sshuser list --status active
cat $KUBE_SSHUSER_OUT_DIR/_registry/events.ndjson | tail
```

学生に案内する側（SSH コンテナの中で打つコマンド。`gpu-dev` は旧名で今学期のみ並走）:

```bash
kube-lab up --gpu 1       # GPU Pod を起動して入る
kube-lab status           # 自分の Pod 一覧
kube-lab down             # 片付け
kube-lab down --all       # 自分の Pod を全部消す
```
