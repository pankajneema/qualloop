"""In-process hook bus (ARCHITECTURE 3.1 rule 3): reactions inside the caller's transaction.

Used where a lower module must trigger a higher one without importing it (for example contact disabled -> links
revoked). Hooks run inside the command's transaction; a failing hook rolls the command back. P01 only provides the bus.
"""

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

Hook = Callable[..., None]

_HOOKS: defaultdict[str, list[Hook]] = defaultdict(list)


def subscribe(name: str, hook: Hook) -> None:
    if hook not in _HOOKS[name]:
        _HOOKS[name].append(hook)


def publish(name: str, session: Session, *args: Any, **kwargs: Any) -> None:
    for hook in list(_HOOKS.get(name, ())):
        hook(session, *args, **kwargs)
