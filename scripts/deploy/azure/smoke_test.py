"""Smoke-test a TripGenie cloud deployment through its public frontends.

    python scripts/deploy/azure/smoke_test.py URL [URL ...]

Takes the frontend URLs deploy.sh prints. Every page must load, Student 1 must
complete a trip create -> read -> delete round trip through its frontend, the
backends and databases behind it, and the RAG panel must report the AI service
disabled, as the cloud baseline requires. Every page must also carry the
security headers and hide its server software; over HTTPS, plain HTTP must
redirect and no backend or database may answer from the internet. Prints a
Markdown table for the GitHub job summary and exits non-zero on any failure.
Stdlib only.
"""

import itertools
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


opener = urllib.request.build_opener(NoRedirect)

SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(),microphone=(),geolocation=()",
}


def request(url, form=None):
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    try:
        # Frontends scale to zero, so the first hit can include a cold start of
        # the whole frontend -> backend -> database chain.
        with opener.open(url, data=data, timeout=120) as response:
            return response.status, response.read().decode(errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")
    # socket.timeout is TimeoutError only from Python 3.10; macOS ships 3.9.
    except (TimeoutError, socket.timeout, urllib.error.URLError) as error:  # noqa: UP041
        return f"no response ({error})", ""


def headers_of(url):
    try:
        with opener.open(url, timeout=120) as response:
            return response.status, response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.headers
    except (TimeoutError, socket.timeout, urllib.error.URLError) as error:  # noqa: UP041
        return f"no response ({error})", {}


def wake(url):
    # A freshly deployed or idle chain can need more than one request timeout to
    # start every replica behind it, so a page gets three tries.
    for _ in range(3):
        status, body = request(url)
        if status == 200:
            break
    return status, body


def checks(urls):
    for url in urls:
        status, _ = wake(url)
        yield f"GET {url}", status == 200, status

    # The compose port lets the same checks run against a local stack too.
    s1 = next(
        (u for u in urls if "student-1-frontend" in u or u.endswith(":8081")), None
    )
    if s1 is None:
        yield "Student 1 frontend deployed", False, "missing"
        return
    trip = f"trip_smoke_{int(time.time())}"
    status, _ = request(
        f"{s1}/trips",
        {
            "id": trip,
            "name": "Cloud smoke test",
            "destination": "Sydney",
            "start_date": "2026-12-01",
            "end_date": "2026-12-03",
            "traveller_count": "1",
            "status": "planned",
            "notes": "",
        },
    )
    yield "Create trip (POST /trips)", status == 303, status
    status, body = request(f"{s1}/trips/{trip}")
    found = status == 200 and "Cloud smoke test" in body
    yield "Read trip (GET /trips/{id})", found, status
    status, _ = request(f"{s1}/trips/{trip}/rag-query", {"question": "What to pack?"})
    yield "RAG disabled in the cloud", status == 503, status
    status, _ = request(f"{s1}/trips/{trip}/delete", {"trip_name": "Cloud smoke test"})
    yield "Delete trip (POST /trips/{id}/delete)", status == 303, status
    status, _ = request(f"{s1}/trips/{trip}")
    yield "Trip gone after delete", status == 404, status


def security_checks(urls):
    internal = []
    for url in urls:
        status, headers = headers_of(url)
        wrong = [k for k, v in SECURITY_HEADERS.items() if headers.get(k) != v]
        detail = "missing " + ", ".join(wrong) if wrong else status
        yield f"Security headers on {url}", status == 200 and not wrong, detail
        server = headers.get("Server") or ""
        yield f"Server software hidden on {url}", server in ("", "nginx"), server

        scheme, _, rest = url.partition("://")
        if scheme != "https":
            continue
        status, headers = headers_of(f"http://{rest}")
        to_https = (headers.get("Location") or "").startswith("https://")
        yield (
            f"HTTP redirects to HTTPS on {rest}",
            status in (301, 308) and to_https,
            status,
        )
        app, _, domain = rest.partition("/")[0].partition(".")
        service = "shared" if app == "shared-ui" else app.removesuffix("-frontend")
        internal += [f"{service}-backend.{domain}", f"{service}-database.{domain}"]

    for host in internal:
        status, _ = headers_of(f"https://{host}/health")
        yield f"Not public: {host}", status != 200, status


def main(urls):
    urls = [u.rstrip("/") for u in urls if u]
    print("| Check | Result | HTTP |\n| --- | --- | --- |")
    failed = 0
    for name, ok, status in itertools.chain(checks(urls), security_checks(urls)):
        failed += not ok
        print(f"| {name} | {'pass' if ok else 'FAIL'} | {status} |", flush=True)
    return 1 if failed or not urls else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
