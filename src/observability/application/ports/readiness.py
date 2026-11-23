from collections.abc import Awaitable, Callable

type Probe = Callable[[], Awaitable[bool]]
