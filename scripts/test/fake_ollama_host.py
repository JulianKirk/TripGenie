from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_MODEL = "qwen2.5:0.5b"
REQUESTED_DATE_PATTERN = re.compile(r'"requested_date"\s*:\s*"(\d{4}-\d{2}-\d{2})"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a tiny test-only Ollama-compatible host process for Compose smoke."
        )
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=11434)
    return parser.parse_args()


def extract_requested_date(prompt: str) -> str:
    match = REQUESTED_DATE_PATTERN.search(prompt)
    if match is None:
        return "2026-10-03"
    return match.group(1)


class FakeOllamaHandler(BaseHTTPRequestHandler):
    server_version = "TripGenieFakeOllama/1.0"

    def log_message(self, message_format: str, *args: object) -> None:
        del message_format, args

    def do_GET(self) -> None:
        if self.path != "/api/tags":
            self.respond_json(404, {"error": "not found"})
            return

        self.respond_json(
            200,
            {
                "models": [
                    {
                        "name": DEFAULT_MODEL,
                        "model": DEFAULT_MODEL,
                        "modified_at": "2026-09-01T00:00:00Z",
                        "size": 934348800,
                        "digest": "sha256:tripgenie-fake-ollama",
                        "details": {"family": "qwen2"},
                    }
                ]
            },
        )

    def do_POST(self) -> None:
        if self.path != "/api/generate":
            self.respond_json(404, {"error": "not found"})
            return

        payload = self.read_json_body()
        if payload is None:
            self.respond_json(400, {"error": "invalid json"})
            return

        requested_date = extract_requested_date(str(payload.get("prompt", "")))
        model = str(payload.get("model") or DEFAULT_MODEL)
        response_text = json.dumps(
            {
                "suggestions": [
                    {
                        "date": requested_date,
                        "start_time": "12:30",
                        "end_time": "14:00",
                        "title": "CI Fake Harbour Lunch",
                        "location": "The Rocks",
                        "description": (
                            "Test-only fake Ollama transport suggestion for "
                            "Release 0 smoke."
                        ),
                        "category": "meal",
                        "notes": "Transport-contract only; review before saving.",
                        "rationale": "Provides a deterministic midday draft.",
                    }
                ]
            },
            separators=(",", ":"),
        )
        self.respond_json(
            200,
            {
                "model": model,
                "created_at": "2026-09-01T00:00:00Z",
                "response": response_text,
                "done": True,
                "done_reason": "stop",
                "context": [1, 2, 3],
                "total_duration": 1000000,
                "load_duration": 500000,
                "prompt_eval_count": 42,
                "prompt_eval_duration": 250000,
                "eval_count": 128,
                "eval_duration": 250000,
            },
        )

    def read_json_body(self) -> dict[str, object] | None:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except ValueError:
            return None

        if not isinstance(payload, dict):
            return None
        return payload

    def respond_json(self, status_code: int, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> int:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), FakeOllamaHandler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
