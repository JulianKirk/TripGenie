"""Tests for the shared deterministic CI readiness probe."""

from __future__ import annotations

import importlib.util
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "wait_for_http.py"


def load_probe_module():
    assert SCRIPT.exists(), "the shared readiness probe has not been implemented"
    spec = importlib.util.spec_from_file_location("wait_for_http", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_waits_two_seconds_between_at_most_eight_attempts() -> None:
    wait_for_http = load_probe_module()
    attempts = iter([False] * 7 + [True])
    sleeps: list[float] = []
    messages: list[str] = []

    passed = wait_for_http.wait_until_ready(
        "http://service.test/health",
        "example service",
        probe=lambda _url, _contains: next(attempts),
        sleep=sleeps.append,
        clock=iter([100.0, 114.0]).__next__,
        output=messages.append,
    )

    assert passed is True
    assert sleeps == [2.0] * 7
    assert messages[-1] == (
        "PASS: example service responded on attempt 8/8 after 14.00s "
        "(each request limited to 2s)"
    )


def test_fails_after_eight_attempts_without_an_extra_sleep() -> None:
    wait_for_http = load_probe_module()
    sleeps: list[float] = []
    messages: list[str] = []

    passed = wait_for_http.wait_until_ready(
        "http://service.test/health",
        "example service",
        probe=lambda _url, _contains: False,
        sleep=sleeps.append,
        clock=iter([10.0, 24.0]).__next__,
        output=messages.append,
    )

    assert passed is False
    assert sleeps == [2.0] * 7
    assert messages[-1] == (
        "FAIL: example service did not respond after 8 attempts at 2s intervals "
        "(14.00s elapsed)"
    )


def test_http_probe_requires_success_status_and_expected_body() -> None:
    wait_for_http = load_probe_module()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ready"}')

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/health"

    try:
        assert wait_for_http.http_probe(url, '"status":"ready"') is True
        assert wait_for_http.http_probe(url, '"status":"ok"') is False
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
