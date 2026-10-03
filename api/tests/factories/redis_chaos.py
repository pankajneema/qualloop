"""A Redis client that lets a test inject "something else happened in between" deterministically.

`ChaosRedis` shares the connection pool of a real client and, after the FIRST command that satisfies `match`
(directly, as an immediate pipeline command such as WATCH/GET, or as part of an executed pipeline), runs `action`
exactly once. This turns a read-modify-write race into a plain, repeatable sequence without sleeps or threads.
"""

from collections.abc import Callable, Sequence
from typing import Any

import redis
from redis.client import Pipeline

Match = Callable[[Sequence[Any]], bool]


def key_command(key: str, *names: str) -> Match:
    """Match a command on `key` (any command when `names` is empty, otherwise only those, case-insensitive)."""
    wanted = {n.upper() for n in names}

    def match(args: Sequence[Any]) -> bool:
        if not args or key not in [str(a) for a in args[1:]]:
            return False
        return not wanted or str(args[0]).upper() in wanted

    return match


class ChaosRedis(redis.Redis):
    """Build with `ChaosRedis.sharing(real_client)`, then call `arm(match, action)`."""

    _match: Match | None = None
    _action: Callable[[], None] | None = None
    fired_by: str | None = None

    @classmethod
    def sharing(cls, client: redis.Redis) -> "ChaosRedis":
        return cls(connection_pool=client.connection_pool)

    def arm(self, match: Match, action: Callable[[], None]) -> None:
        self._match, self._action, self.fired_by = match, action, None

    def observe(self, args: Sequence[Any]) -> None:
        if self._action is None or self._match is None or not self._match(args):
            return
        action, self._action = self._action, None  # once; also guards against recursion
        self.fired_by = str(args[0]).upper()
        action()

    def execute_command(self, *args: Any, **options: Any) -> Any:
        result = super().execute_command(*args, **options)  # type: ignore[no-untyped-call]
        self.observe(args)
        return result

    def pipeline(self, transaction: bool = True, shard_hint: Any = None) -> Pipeline:
        return _ChaosPipeline(
            self, self.connection_pool, self.response_callbacks, transaction, shard_hint
        )


class _ChaosPipeline(Pipeline):
    def __init__(self, chaos: ChaosRedis, *args: Any) -> None:
        super().__init__(*args)
        self._chaos = chaos

    def immediate_execute_command(self, *args: Any, **options: Any) -> Any:
        result = super().immediate_execute_command(*args, **options)  # type: ignore[no-untyped-call]
        self._chaos.observe(args)
        return result

    def execute(self, raise_on_error: bool = True) -> Any:
        queued = [command[0] for command in self.command_stack]
        result = super().execute(raise_on_error)
        for args in queued:
            self._chaos.observe(args)
        return result
