#!/usr/bin/env python3
"""Label and annotation keys for the resources this tool manages.

Every managed resource is found again by these keys: `status`, `doctor`,
`terminate-pod` and `delete-user` all build selectors from them. They were
previously spelled out as literals in six modules, in two different shapes
(a joined "key=value" selector string in some places, separate key and value
constants in others), so a rename could be applied to five of them and silently
missed in the sixth -- which would leave orphaned resources behind.

The values are deliberately unchanged. `provision-user.openai.local` is wrong
(it is not this lab's domain) but it is baked into every namespace, PVC,
Deployment and Service currently running, so replacing it needs a read-both /
write-both migration rather than an edit. Naming it in one place is what makes
that migration a one-file change later.
"""

# --- keys -------------------------------------------------------------------

MANAGED_BY_KEY = "app.kubernetes.io/managed-by"
MANAGED_BY_VALUE = "provision-user"

APP_NAME_KEY = "app.kubernetes.io/name"
SSH_APP_NAME_VALUE = "ssh-user"

LABEL_DOMAIN = "provision-user.openai.local"

USER_LABEL_KEY = f"{LABEL_DOMAIN}/user"
DISPLAY_NAME_ANNOTATION = f"{LABEL_DOMAIN}/display-name"
DESCRIPTION_ANNOTATION = f"{LABEL_DOMAIN}/description"


# --- selectors --------------------------------------------------------------


def selector(*pairs: tuple[str, str]) -> str:
    """Join label key/value pairs into a kubectl -l selector."""
    return ",".join(f"{key}={value}" for key, value in pairs)


MANAGED_NAMESPACE_SELECTOR = selector((MANAGED_BY_KEY, MANAGED_BY_VALUE))
SSH_APP_SELECTOR = selector((APP_NAME_KEY, SSH_APP_NAME_VALUE))


def user_selector(username: str) -> str:
    """Select every managed resource belonging to one user."""
    return selector(
        (MANAGED_BY_KEY, MANAGED_BY_VALUE),
        (USER_LABEL_KEY, username),
    )
