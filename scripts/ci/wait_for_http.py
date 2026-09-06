#!/usr/bin/env python3
"""Apply TripGenie's minimum deterministic HTTP readiness policy."""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


ATTEMPTS = 8
INTERVAL_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 2.0


def http_probe(url: str, contains: str | None) -> bool:
    """Return whether a successful response optionally contains required text."""
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (OSError, urllib.error.HTTPError, urllib.error.URLError):
        return False
    return contains is None or contains in body


def wait_until_ready(
    url: str,
    label: str,
    contains: str | None = None,
    *,
    probe: Callable[[str, str | None], bool] = http_probe,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    output: Callable[[str], None] = print,
) -> bool:
    """Probe using the repository-wide eight-attempt, two-second policy."""
    started = clock()
    for attempt in range(1, ATTEMPTS + 1):
        output(f"Probe {attempt}/{ATTEMPTS}: {label} ({url})")
        if probe(url, contains):
            elapsed = clock() - started
            output(
                f"PASS: {label} responded on attempt {attempt}/{ATTEMPTS} "
                f"after {elapsed:.2f}s (each request limited to "
                f"{REQUEST_TIMEOUT_SECONDS:g}s)"
            )
            return True
        if attempt < ATTEMPTS:
            sleep(INTERVAL_SECONDS)

    elapsed = clock() - started
    output(
        f"FAIL: {label} did not respond after {ATTEMPTS} attempts at "
        f"{INTERVAL_SECONDS:g}s intervals ({elapsed:.2f}s elapsed)"
    )
    return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wait for an HTTP endpoint using TripGenie's fixed CI policy."
    )
    parser.add_argument("url", help="Health or readiness endpoint to probe")
    parser.add_argument("--label", required=True, help="Service name for CI output")
    parser.add_argument(
        "--contains", help="Optional response substring required for readiness"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return 0 if wait_until_ready(args.url, args.label, args.contains) else 1


if __name__ == "__main__":
    sys.exit(main())
