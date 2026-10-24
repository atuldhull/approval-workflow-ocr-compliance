"""Port registry: each module's wiring.py provides its implementations; callers look them up by port type."""
from typing import TypeVar

T = TypeVar("T")

_impls: dict[type, object] = {}


def provide(port_type: type[T], impl: T) -> None:
    if not isinstance(impl, port_type):
        raise TypeError(f"{type(impl).__name__} does not implement {port_type.__name__}")
    _impls[port_type] = impl


def port(port_type: type[T]) -> T:
    try:
        return _impls[port_type]  # type: ignore[return-value]
    except KeyError:
        raise RuntimeError(f"No implementation wired for {port_type.__name__}") from None
