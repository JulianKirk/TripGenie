"""Host bindings and public backend addresses."""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8012
    urls: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = {
            "student-1": "http://127.0.0.1:18001",
            "student-2": "http://127.0.0.1:9000",
            "student-3": "http://127.0.0.1:18003",
            "student-4": "http://127.0.0.1:18008",
            "student-5": "http://127.0.0.1:18005",
        }
        urls = {
            name: os.getenv(f"MCP_{name.upper().replace('-', '_')}_URL", url).rstrip(
                "/"
            )
            for name, url in defaults.items()
        }
        return cls(
            host=os.getenv("MCP_HOST", "127.0.0.1"),
            port=int(os.getenv("MCP_PORT", "8012")),
            urls=urls,
        )
