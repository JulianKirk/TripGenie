from __future__ import annotations


class FrontendError(Exception):
    """A backend failure safe to translate into an HTML state."""

    def __init__(self, *, kind: str, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.status_code = status_code
        self.detail = detail
