#!/usr/bin/env python3
"""What this CLI calls itself.

The tool was renamed from `gpu-dev` to `kube-lab`, and both names are installed
as entry points for one semester so nobody's notes stop working mid-term. Which
name the user typed decides two things: the message prefix, and the commands we
suggest back to them. Suggesting `kube-lab down` to someone who typed `gpu-dev`
sends them to a command their notes do not mention, so the messages follow the
name that was actually invoked.

Resource labels are a different matter: pods still carry `app: gpu-dev` and
`gpu-dev/*` annotations, and those are NOT renamed here. Running pods have them
and `down --all` selects on them; that migration is Phase 6.
"""

import sys
from pathlib import Path

CANONICAL_NAME = "kube-lab"
LEGACY_NAME = "gpu-dev"


def invoked_name() -> str:
    """The name this process was started as, or the canonical name."""
    name = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else ""
    return name if name in {CANONICAL_NAME, LEGACY_NAME} else CANONICAL_NAME


PROG = invoked_name()
TAG = f"[{PROG}]"


def warn_if_legacy_name() -> None:
    """Tell the user about the rename, once, when invoked as the old name."""
    if PROG != LEGACY_NAME:
        return
    print(
        f"[{LEGACY_NAME}] note: this command has been renamed to "
        f"`{CANONICAL_NAME}`. `{LEGACY_NAME}` still works this semester and "
        f"will be removed after it.",
        file=sys.stderr,
    )
