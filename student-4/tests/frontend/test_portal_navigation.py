from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


class PortalLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: dict[str, str] = {}
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links[" ".join("".join(self._text).split())] = self._href
            self._href = None


def test_shared_portal_opens_the_student_4_frontend() -> None:
    portal = PortalLinks()
    repository = Path(__file__).resolve().parents[3]
    portal.feed((repository / "shared/frontend/index.html").read_text())

    student_4 = next(
        href for label, href in portal.links.items() if label.startswith("Student 4")
    )
    assert student_4 == "http://localhost:8094"
