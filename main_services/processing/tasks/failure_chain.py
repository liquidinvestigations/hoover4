"""Read exception causes without discarding cancellations or nested failures."""


def exception_chain(exc: BaseException):
    """Yield each exception once, including SDK causes."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        cause = current.__cause__ or getattr(current, "cause", None)
        current = cause if isinstance(cause, BaseException) else None


def is_cancellation(exc: BaseException) -> bool:
    """Return whether the exception chain contains a cancellation."""
    return any(type(item).__name__ == "CancelledError" for item in exception_chain(exc))


def failure_message(exc: BaseException) -> str:
    """Return the complete exception chain for stored failure evidence."""
    return " <- ".join(f"{type(item).__name__}: {item}" for item in exception_chain(exc))
