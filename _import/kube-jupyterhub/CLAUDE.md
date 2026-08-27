# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Format
isort .
black .

# Lint / type check
flake8 .
mypy kube_jupyterhub/

# Test
pytest
```

## Architecture

`kube-jupyterhub` is a zero-dependency Python CLI that wraps `kubectl` and `helm` for managing JupyterHub on Kubernetes (k3s). All logic lives in a single module: `kube_jupyterhub/cli.py`.

**Entry point**: `kube-jupyterhub` → `cli.main()`

**Structure inside `cli.py`**:
- `run()` — the single execution path. Logs `[cmd] <argv>` to stderr, injects the
  `--context` flag, and honours `--dry-run`. **Every external command goes through it**
  (`prepull_images()` used to call `subprocess.run()` directly and so escaped both).
- `apply_config()` — runs `helm upgrade --install`, optionally waits for rollout
- `refresh_user()` / `refresh_full_user()` — delete user pod (and optionally PVC) then wait for restart
- `list_users()` / `pvc_list()` — `kubectl get` with custom columns

**Defaults** (all overridable via CLI flags):
- namespace: `jupyterhub`
- Helm release: `jupyterhub`
- values file: `config.yaml` (expected in the working directory)

**Subcommands**: `apply`, `list`, `pvc`, `refresh <username>`, `refresh-full <username>`

**グローバルフラグ**（`-n/--namespace` の他に）:

- `--context` — 接続先クラスタの指定。**kubectl は `--context`、helm は `--kube-context`**
  とフラグ名が違うので、`CONTEXT_FLAGS` テーブルでコマンド名から引いている。
- `--dry-run` — 実行せず `[dry-run] <argv>` を出すだけ。

**`refresh-full` は typed confirm。** 学生の PVC を消す唯一の経路なので、y/N ではなく
**PVC 名（`claim-<user>`）を正確に打たせる**。不一致なら exit 1（＝スクリプトから
「中止された」と「完了した」を区別できる）。`-y` で省略可。

The tool has no runtime library dependencies — only Python stdlib (`argparse`, `subprocess`, `shlex`, `sys`). Dev extras (`pytest`, `black`, `isort`, `flake8`, `mypy`) are declared under `[project.optional-dependencies] dev` in `pyproject.toml`. Version is managed by `setuptools_scm`.
