"""Bound recoverable extraction details without losing their total count."""


def short_name(value: object) -> str:
    return str(value).encode("utf-8")[:200].decode("utf-8", "ignore")


class ErrorSamples(list):
    def __init__(self):
        super().__init__()
        self.total = 0

    def append(self, value):
        self.total += 1
        if len(self) < 20:
            super().append(short_name(value))
