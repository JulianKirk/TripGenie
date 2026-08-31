from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
BASE_ENV_FILE = REPO_ROOT / "shared" / "configuration" / ".env.example"
GENERATED_ENV_DIR = REPO_ROOT / "scripts" / "test"

SHARED_UI_URL = "http://127.0.0.1:8080/"
STUDENT1_FRONTEND_URL = "http://127.0.0.1:8081/"
SEEDED_AI_TRIP_ID = "trip_2026_sydney_long_weekend"
SEEDED_AI_DATE = "2026-10-03"
FAKE_AI_TITLE = "CI Fake Harbour Lunch"

SMOKE_SERVICES = (
    "shared-ui",
    "student-1-database",
    "student-1-backend",
    "student-1-frontend",
    "ai-mode",
)
UNPUBLISHED_INTERNAL_PORTS = (
    ("student-1-backend", "8001"),
    ("student-1-database", "8002"),
    ("ai-mode", "8006"),
)

HTTP_TIMEOUT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 1.0
WAIT_TIMEOUT_SECONDS = 120.0
DEGRADED_OLLAMA_BASE_URL = "http://host.docker.internal:65531"
HOST_OLLAMA_BASE_URL = "http://host.docker.internal:11434"
FAKE_OLLAMA_HOST_URL = "http://127.0.0.1:11434/api/tags"

SERVICE_HTTP_PROBE_SCRIPT = """
import json
import sys
import urllib.error
import urllib.request

url = sys.argv[1]
timeout = float(sys.argv[2])
request = urllib.request.Request(url, method="GET")
try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        print(json.dumps({"status_code": response.status, "body": body}))
except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8")
    print(json.dumps({"status_code": exc.code, "body": body}))
"""


class SmokeError(RuntimeError):
    """Raised when Compose smoke validation fails."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    body: str
    headers: dict[str, str]
    url: str


@dataclass(frozen=True, slots=True)
class PhaseConfig:
    name: str
    description: str
    env_overrides: dict[str, str]
    start_fake_ollama: bool = False
    expected_ai_health_status: str = "degraded"
    expected_ai_ready_status: int = 503
    expected_backend_health_status: str = "degraded"


ROUTINE_PHASES = ("degraded-unavailable", "fake-ollama-transport")
PHASES = {
    "degraded-unavailable": PhaseConfig(
        name="degraded-unavailable",
        description="force unavailable host Ollama while CRUD still works",
        env_overrides={
            "AI_MODE_OLLAMA_BASE_URL": DEGRADED_OLLAMA_BASE_URL,
            "AI_MODE_TIMEOUT_SECONDS": "2",
        },
        expected_ai_health_status="degraded",
        expected_ai_ready_status=503,
        expected_backend_health_status="degraded",
    ),
    "fake-ollama-transport": PhaseConfig(
        name="fake-ollama-transport",
        description="use a fake host Ollama process for transport-contract CI",
        env_overrides={
            "AI_MODE_OLLAMA_BASE_URL": HOST_OLLAMA_BASE_URL,
            "AI_MODE_TIMEOUT_SECONDS": "5",
        },
        start_fake_ollama=True,
        expected_ai_health_status="ok",
        expected_ai_ready_status=200,
        expected_backend_health_status="ok",
    ),
    "live-host-ollama": PhaseConfig(
        name="live-host-ollama",
        description="use an already-running real host Ollama for manual evidence",
        env_overrides={
            "AI_MODE_OLLAMA_BASE_URL": HOST_OLLAMA_BASE_URL,
            "AI_MODE_TIMEOUT_SECONDS": "5",
        },
        expected_ai_health_status="ok",
        expected_ai_ready_status=200,
        expected_backend_health_status="ok",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deterministic Student 1 Compose smoke validation."
    )
    parser.add_argument(
        "--project-name",
        help=(
            "Unique Compose project name. Defaults to an issue-14-specific random "
            "value."
        ),
    )
    parser.add_argument(
        "--env-file",
        default=str(BASE_ENV_FILE),
        help="Base Compose env file to extend per smoke phase.",
    )
    parser.add_argument(
        "--phase",
        action="append",
        choices=sorted(PHASES),
        help=(
            "Phase(s) to run. Defaults to the routine degraded + fake transport "
            "pair used in CI."
        ),
    )
    return parser.parse_args()


def emit(message: str) -> None:
    print(f"[compose-smoke] {message}", flush=True)


def fail(message: str) -> None:
    raise SmokeError(message)


def ensure(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def make_project_name(user_supplied: str | None) -> str:
    if user_supplied:
        return user_supplied
    return f"tripgenie14-{uuid4().hex[:10]}"


def safe_file_stem(value: str) -> str:
    collapsed = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return collapsed or "compose-smoke"


def format_command(command: list[str]) -> str:
    return " ".join(command)


def tail_text(text: str, *, max_lines: int = 80) -> str:
    lines = text.strip().splitlines()
    if len(lines) <= max_lines:
        return text.strip()
    return "\n".join(lines[-max_lines:])


def run_command(
    command: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        stdout = tail_text(result.stdout)
        stderr = tail_text(result.stderr)
        details = [f"command failed: {format_command(command)}"]
        if stdout:
            details.append(f"stdout:\n{stdout}")
        if stderr:
            details.append(f"stderr:\n{stderr}")
        fail("\n".join(details))
    return result


def compose_command(project_name: str, env_file: Path, *args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-p",
        project_name,
        "-f",
        str(COMPOSE_FILE),
        "--env-file",
        str(env_file),
        *args,
    ]


def write_phase_env_file(
    base_env_file: Path,
    *,
    project_name: str,
    phase: PhaseConfig,
) -> Path:
    base_text = base_env_file.read_text(encoding="utf-8").rstrip()
    env_path = GENERATED_ENV_DIR / (
        f".compose-smoke.{safe_file_stem(project_name)}."
        f"{safe_file_stem(phase.name)}.env"
    )
    lines = [base_text, "", f"# Generated for compose smoke phase {phase.name}"]
    for key, value in sorted(phase.env_overrides.items()):
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_path


def fetch_url(
    url: str,
    *,
    form_data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> HttpResponse:
    encoded_body = None
    request_headers = dict(headers or {})
    if form_data is not None:
        encoded_body = urllib.parse.urlencode(form_data).encode("utf-8")
        request_headers.setdefault(
            "Content-Type",
            "application/x-www-form-urlencoded",
        )
    request = urllib.request.Request(
        url,
        data=encoded_body,
        headers=request_headers,
        method="POST" if encoded_body is not None else "GET",
    )
    opener = urllib.request.build_opener()
    try:
        with opener.open(request, timeout=timeout) as response:
            return HttpResponse(
                status_code=response.status,
                body=response.read().decode("utf-8"),
                headers=dict(response.headers.items()),
                url=response.geturl(),
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(
            status_code=exc.code,
            body=exc.read().decode("utf-8"),
            headers=dict(exc.headers.items()),
            url=exc.geturl(),
        )
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        fail(f"HTTP request to {url} failed: {reason}")


def parse_json_body(response: HttpResponse, *, context: str) -> Any:
    try:
        return json.loads(response.body)
    except json.JSONDecodeError as exc:
        fail(
            f"{context} returned malformed JSON (HTTP {response.status_code}): {exc}"
        )


def extract_envelope_data(response: HttpResponse, *, context: str) -> Any:
    payload = parse_json_body(response, context=context)
    ensure(isinstance(payload, dict), f"{context} did not return a JSON object")
    ensure("data" in payload, f"{context} did not return a data envelope")
    return payload["data"]


def mapping(value: Any, *, context: str) -> dict[str, Any]:
    ensure(isinstance(value, dict), f"{context} must be a JSON object")
    return value


def response_path(response: HttpResponse) -> str:
    return urllib.parse.urlparse(response.url).path


def require_path_suffix(response: HttpResponse, expected_suffix: str) -> None:
    actual_path = response_path(response)
    ensure(
        actual_path.endswith(expected_suffix),
        f"expected final path '{expected_suffix}', got '{actual_path}'",
    )


def require_contains(body: str, *fragments: str, context: str) -> None:
    for fragment in fragments:
        ensure(fragment in body, f"{context} is missing expected fragment: {fragment}")


def compose_service_get(
    project_name: str,
    env_file: Path,
    *,
    service: str,
    url: str,
) -> HttpResponse:
    command = compose_command(
        project_name,
        env_file,
        "exec",
        "-T",
        service,
        "python",
        "-c",
        SERVICE_HTTP_PROBE_SCRIPT,
        url,
        str(HTTP_TIMEOUT_SECONDS),
    )
    result = run_command(command, check=False)
    if result.returncode != 0:
        stdout = tail_text(result.stdout)
        stderr = tail_text(result.stderr)
        details = [
            f"unable to probe {service} at {url}",
            f"command: {format_command(command)}",
        ]
        if stdout:
            details.append(f"stdout:\n{stdout}")
        if stderr:
            details.append(f"stderr:\n{stderr}")
        fail("\n".join(details))

    probe_response = HttpResponse(
        status_code=200,
        body=result.stdout.strip(),
        headers={},
        url=url,
    )
    payload = parse_json_body(probe_response, context=f"{service} HTTP probe")
    payload_mapping = mapping(payload, context=f"{service} HTTP probe payload")
    status_code = payload_mapping.get("status_code")
    body = payload_mapping.get("body")
    ensure(
        isinstance(status_code, int),
        f"{service} probe status_code must be an integer",
    )
    ensure(isinstance(body, str), f"{service} probe body must be a string")
    return HttpResponse(status_code=status_code, body=body, headers={}, url=url)


def wait_for_probe(
    description: str,
    probe: Callable[[], HttpResponse],
    *,
    expected_statuses: set[int],
    predicate: Callable[[HttpResponse], bool] | None = None,
    timeout_seconds: float = WAIT_TIMEOUT_SECONDS,
) -> HttpResponse:
    deadline = time.monotonic() + timeout_seconds
    last_observation = "no observation captured"
    while time.monotonic() < deadline:
        try:
            response = probe()
            if response.status_code in expected_statuses and (
                predicate is None or predicate(response)
            ):
                return response
            last_observation = (
                f"HTTP {response.status_code} with body: "
                f"{tail_text(response.body, max_lines=10)}"
            )
        except Exception as exc:  # noqa: BLE001
            last_observation = str(exc)
        time.sleep(POLL_INTERVAL_SECONDS)
    fail(
        f"{description} did not become ready within {timeout_seconds:.0f}s. "
        f"Last observation: {last_observation}"
    )
    unreachable_message = "unreachable"
    raise AssertionError(unreachable_message)


def backend_get(project_name: str, env_file: Path, path: str) -> HttpResponse:
    return compose_service_get(
        project_name,
        env_file,
        service="student-1-backend",
        url=f"http://127.0.0.1:8001{path}",
    )


def database_get(project_name: str, env_file: Path, path: str) -> HttpResponse:
    return compose_service_get(
        project_name,
        env_file,
        service="student-1-database",
        url=f"http://127.0.0.1:8002{path}",
    )


def ai_mode_get(project_name: str, env_file: Path, path: str) -> HttpResponse:
    return compose_service_get(
        project_name,
        env_file,
        service="ai-mode",
        url=f"http://127.0.0.1:8006{path}",
    )


def wait_for_shared_ui() -> HttpResponse:
    return wait_for_probe(
        "shared portal root",
        lambda: fetch_url(SHARED_UI_URL),
        expected_statuses={200},
    )


def wait_for_database_health(project_name: str, env_file: Path) -> HttpResponse:
    def predicate(response: HttpResponse) -> bool:
        data = mapping(
            extract_envelope_data(response, context="database health"),
            context="database health data",
        )
        return data.get("status") == "ok"

    return wait_for_probe(
        "student-1 database health",
        lambda: database_get(project_name, env_file, "/internal/health"),
        expected_statuses={200},
        predicate=predicate,
    )


def wait_for_backend_ready(project_name: str, env_file: Path) -> HttpResponse:
    def predicate(response: HttpResponse) -> bool:
        data = mapping(
            extract_envelope_data(response, context="backend ready"),
            context="backend ready data",
        )
        return data.get("status") == "ok"

    return wait_for_probe(
        "student-1 backend readiness",
        lambda: backend_get(project_name, env_file, "/ready"),
        expected_statuses={200},
        predicate=predicate,
    )


def wait_for_frontend_ready() -> HttpResponse:
    def predicate(response: HttpResponse) -> bool:
        data = mapping(
            extract_envelope_data(response, context="frontend ready"),
            context="frontend ready data",
        )
        return data.get("status") == "ok"

    return wait_for_probe(
        "student-1 frontend readiness",
        lambda: fetch_url(urllib.parse.urljoin(STUDENT1_FRONTEND_URL, "ready")),
        expected_statuses={200},
        predicate=predicate,
    )


def verify_port_exposure(project_name: str, env_file: Path) -> None:
    for service, port in UNPUBLISHED_INTERNAL_PORTS:
        result = run_command(
            compose_command(project_name, env_file, "port", service, port),
            check=False,
        )
        ensure(
            result.returncode != 0 and not result.stdout.strip(),
            f"{service} unexpectedly published host port {port}: "
            f"{result.stdout.strip()}",
        )


def verify_portal_and_seeded_frontend(
    project_name: str,
    env_file: Path,
) -> dict[str, str]:
    portal_response = fetch_url(SHARED_UI_URL)
    ensure(
        portal_response.status_code == 200,
        f"shared portal returned HTTP {portal_response.status_code}",
    )
    require_contains(
        portal_response.body,
        "Student 1: Trip &amp; Itinerary Management",
        "http://localhost:8081",
        context="shared portal",
    )

    trips_response = backend_get(project_name, env_file, "/api/trips")
    ensure(
        trips_response.status_code == 200,
        f"backend trip list returned HTTP {trips_response.status_code}",
    )
    trips_data = extract_envelope_data(trips_response, context="backend trip list")
    ensure(isinstance(trips_data, list) and trips_data, "backend trip list is empty")
    first_trip = mapping(trips_data[0], context="first backend trip")
    first_trip_id = str(first_trip["id"])
    first_trip_name = str(first_trip["name"])
    first_trip_destination = str(first_trip["destination"])

    detail_path = f"/api/trips/{first_trip_id}"
    trip_detail_response = backend_get(project_name, env_file, detail_path)
    ensure(
        trip_detail_response.status_code == 200,
        f"backend trip detail returned HTTP {trip_detail_response.status_code}",
    )
    trip_detail = mapping(
        extract_envelope_data(trip_detail_response, context="backend trip detail"),
        context="backend trip detail data",
    )
    seeded_item_title = ""
    for day in trip_detail.get("days", []):
        if not isinstance(day, dict):
            continue
        items = day.get("items")
        if not isinstance(items, list) or not items:
            continue
        first_item = mapping(items[0], context="seeded itinerary item")
        seeded_item_title = str(first_item["title"])
        break

    frontend_response = fetch_url(STUDENT1_FRONTEND_URL)
    ensure(
        frontend_response.status_code == 200,
        f"student-1 frontend returned HTTP {frontend_response.status_code}",
    )
    require_contains(
        frontend_response.body,
        first_trip_name,
        first_trip_destination,
        context="student-1 frontend dashboard",
    )
    if seeded_item_title:
        require_contains(
            frontend_response.body,
            seeded_item_title,
            context="student-1 frontend seeded trip detail",
        )
    ensure(
        "sqlite_path" not in frontend_response.body,
        "frontend unexpectedly exposed sqlite_path details",
    )
    return {
        "first_trip_id": first_trip_id,
        "first_trip_name": first_trip_name,
        "seeded_item_title": seeded_item_title,
    }


def status_value(response: HttpResponse, *, context: str) -> str:
    data = mapping(
        extract_envelope_data(response, context=context),
        context=f"{context} data",
    )
    status = data.get("status")
    ensure(isinstance(status, str), f"{context} did not include a string status")
    return status


def verify_phase_health(
    project_name: str,
    env_file: Path,
    *,
    phase: PhaseConfig,
) -> dict[str, Any]:
    ai_health_response = wait_for_probe(
        f"ai-mode /health for {phase.name}",
        lambda: ai_mode_get(project_name, env_file, "/health"),
        expected_statuses={200},
        predicate=lambda response: status_value(
            response,
            context="ai-mode health",
        )
        == phase.expected_ai_health_status,
    )
    ai_ready_response = wait_for_probe(
        f"ai-mode /ready for {phase.name}",
        lambda: ai_mode_get(project_name, env_file, "/ready"),
        expected_statuses={phase.expected_ai_ready_status},
        predicate=lambda response: status_value(
            response,
            context="ai-mode ready",
        )
        == ("ok" if phase.expected_ai_ready_status == 200 else "unavailable"),
    )
    backend_health_response = wait_for_probe(
        f"student-1 backend /health for {phase.name}",
        lambda: backend_get(project_name, env_file, "/health"),
        expected_statuses={200},
        predicate=lambda response: status_value(
            response,
            context="backend health",
        )
        == phase.expected_backend_health_status,
    )

    database_health_response = database_get(project_name, env_file, "/internal/health")
    backend_ready_response = backend_get(project_name, env_file, "/ready")
    return {
        "database_status": status_value(
            database_health_response,
            context="database health verification",
        ),
        "backend_ready_status": status_value(
            backend_ready_response,
            context="backend ready verification",
        ),
        "backend_health_status": status_value(
            backend_health_response,
            context="backend health verification",
        ),
        "ai_health_status": status_value(
            ai_health_response,
            context="ai health verification",
        ),
        "ai_ready_http": ai_ready_response.status_code,
    }


def verify_degraded_ai_behaviour(project_name: str, env_file: Path) -> None:
    del project_name, env_file
    response = fetch_url(
        urllib.parse.urljoin(
            STUDENT1_FRONTEND_URL,
            f"trips/{SEEDED_AI_TRIP_ID}/ai-suggestions",
        ),
        form_data={
            "requested_date": SEEDED_AI_DATE,
            "goal": "Demonstrate degraded host-Ollama behaviour.",
            "interests": "quiet lookouts",
            "constraints": "keep CRUD available",
            "view_date": SEEDED_AI_DATE,
            "view_category": "",
        },
    )
    ensure(
        response.status_code == 503,
        f"expected degraded AI request to return HTTP 503, got "
        f"{response.status_code}",
    )
    require_contains(
        response.body,
        "The AI provider is unavailable.",
        "Demonstrate degraded host-Ollama behaviour.",
        context="degraded AI frontend response",
    )


def verify_crud_via_frontend(project_name: str, env_file: Path) -> dict[str, str]:
    suffix = uuid4().hex[:8]
    trip_id = f"trip_ci_smoke_{suffix}"
    item_id = f"item_ci_smoke_{suffix}"
    create_trip_response = fetch_url(
        urllib.parse.urljoin(STUDENT1_FRONTEND_URL, "trips"),
        form_data={
            "id": trip_id,
            "name": "CI Compose Smoke Trip",
            "destination": "Canberra",
            "start_date": "2027-05-01",
            "end_date": "2027-05-03",
            "traveller_count": "3",
            "status": "planned",
            "notes": "Created through the frontend smoke flow.",
        },
    )
    ensure(
        create_trip_response.status_code == 200,
        f"trip create flow returned HTTP {create_trip_response.status_code}",
    )
    require_path_suffix(create_trip_response, f"/trips/{trip_id}")
    require_contains(
        create_trip_response.body,
        "CI Compose Smoke Trip",
        "Canberra",
        context="trip create frontend response",
    )
    created_trip_response = backend_get(project_name, env_file, f"/api/trips/{trip_id}")
    ensure(
        created_trip_response.status_code == 200,
        f"backend trip verification returned HTTP {created_trip_response.status_code}",
    )

    create_item_response = fetch_url(
        urllib.parse.urljoin(STUDENT1_FRONTEND_URL, f"trips/{trip_id}/items"),
        form_data={
            "trip_id": trip_id,
            "id": item_id,
            "date": "2027-05-02",
            "start_time": "09:00",
            "end_time": "10:30",
            "title": "Parliament House Visit",
            "location": "Canberra",
            "description": "Tour the public areas before lunch.",
            "category": "activity",
            "notes": "Book tickets ahead of time.",
        },
    )
    ensure(
        create_item_response.status_code == 200,
        f"item create flow returned HTTP {create_item_response.status_code}",
    )
    require_path_suffix(create_item_response, f"/trips/{trip_id}/days/2027-05-02")
    require_contains(
        create_item_response.body,
        "Parliament House Visit",
        context="item create frontend response",
    )
    created_item_response = backend_get(
        project_name,
        env_file,
        f"/api/itinerary-items/{item_id}",
    )
    ensure(
        created_item_response.status_code == 200,
        f"backend item verification returned HTTP {created_item_response.status_code}",
    )

    update_trip_response = fetch_url(
        urllib.parse.urljoin(STUDENT1_FRONTEND_URL, f"trips/{trip_id}/edit"),
        form_data={
            "name": "CI Compose Smoke Trip Updated",
            "destination": "Canberra Region",
            "start_date": "2027-05-01",
            "end_date": "2027-05-04",
            "traveller_count": "4",
            "status": "active",
            "notes": "Updated through the frontend smoke flow.",
        },
    )
    ensure(
        update_trip_response.status_code == 200,
        f"trip update flow returned HTTP {update_trip_response.status_code}",
    )
    require_path_suffix(update_trip_response, f"/trips/{trip_id}")
    require_contains(
        update_trip_response.body,
        "CI Compose Smoke Trip Updated",
        "Canberra Region",
        context="trip update frontend response",
    )
    updated_trip = mapping(
        extract_envelope_data(
            backend_get(project_name, env_file, f"/api/trips/{trip_id}"),
            context="updated backend trip",
        ),
        context="updated backend trip data",
    )
    ensure(
        updated_trip.get("status") == "active",
        "backend trip verification did not observe updated active status",
    )

    update_item_response = fetch_url(
        urllib.parse.urljoin(STUDENT1_FRONTEND_URL, f"items/{item_id}/edit"),
        form_data={
            "trip_id": trip_id,
            "date": "2027-05-02",
            "start_time": "09:00",
            "end_time": "10:45",
            "title": "Parliament House Visit",
            "location": "Canberra",
            "description": "Tour the public areas before lunch.",
            "category": "activity",
            "notes": "Confirm the security queue timing.",
        },
    )
    ensure(
        update_item_response.status_code == 200,
        f"item update flow returned HTTP {update_item_response.status_code}",
    )
    require_path_suffix(update_item_response, f"/trips/{trip_id}/days/2027-05-02")
    require_contains(
        update_item_response.body,
        "Confirm the security queue timing.",
        "10:45",
        context="item update frontend response",
    )
    updated_item = mapping(
        extract_envelope_data(
            backend_get(project_name, env_file, f"/api/itinerary-items/{item_id}"),
            context="updated backend item",
        ),
        context="updated backend item data",
    )
    ensure(
        updated_item.get("end_time") == "10:45",
        "backend item verification did not observe updated end_time",
    )

    delete_item_response = fetch_url(
        urllib.parse.urljoin(STUDENT1_FRONTEND_URL, f"items/{item_id}/delete"),
        form_data={
            "trip_id": trip_id,
            "item_date": "2027-05-02",
            "item_title": "Parliament House Visit",
        },
    )
    ensure(
        delete_item_response.status_code == 200,
        f"item delete flow returned HTTP {delete_item_response.status_code}",
    )
    require_path_suffix(delete_item_response, f"/trips/{trip_id}/days/2027-05-02")
    ensure(
        "Parliament House Visit" not in delete_item_response.body,
        "deleted itinerary item still appears in the frontend response",
    )
    deleted_item_response = backend_get(
        project_name,
        env_file,
        f"/api/itinerary-items/{item_id}",
    )
    ensure(
        deleted_item_response.status_code == 404,
        f"expected backend item delete verification to return 404, got "
        f"{deleted_item_response.status_code}",
    )

    delete_trip_response = fetch_url(
        urllib.parse.urljoin(STUDENT1_FRONTEND_URL, f"trips/{trip_id}/delete"),
        form_data={"trip_name": "CI Compose Smoke Trip Updated"},
    )
    ensure(
        delete_trip_response.status_code == 200,
        f"trip delete flow returned HTTP {delete_trip_response.status_code}",
    )
    ensure(
        "CI Compose Smoke Trip Updated" not in delete_trip_response.body,
        "deleted trip still appears in the frontend response",
    )
    deleted_trip_response = backend_get(project_name, env_file, f"/api/trips/{trip_id}")
    ensure(
        deleted_trip_response.status_code == 404,
        f"expected backend trip delete verification to return 404, got "
        f"{deleted_trip_response.status_code}",
    )
    return {"trip_id": trip_id, "item_id": item_id}


def verify_ai_transport_success(project_name: str, env_file: Path) -> None:
    response = fetch_url(
        urllib.parse.urljoin(
            STUDENT1_FRONTEND_URL,
            f"trips/{SEEDED_AI_TRIP_ID}/ai-suggestions",
        ),
        form_data={
            "requested_date": SEEDED_AI_DATE,
            "goal": "Plan a quiet harbour lunch.",
            "interests": "water views, calm pace",
            "constraints": "keep it low effort",
            "view_date": SEEDED_AI_DATE,
            "view_category": "",
        },
    )
    ensure(
        response.status_code == 200,
        f"expected AI transport-contract request to return HTTP 200, got "
        f"{response.status_code}",
    )
    require_contains(
        response.body,
        "Draft results",
        FAKE_AI_TITLE,
        "Approval required",
        "persisted=false",
        context="fake transport AI frontend response",
    )

    trip_detail = mapping(
        extract_envelope_data(
            backend_get(project_name, env_file, f"/api/trips/{SEEDED_AI_TRIP_ID}"),
            context="backend trip detail after fake AI request",
        ),
        context="backend trip detail after fake AI request data",
    )
    persisted_titles = {
        str(item["title"])
        for day in trip_detail.get("days", [])
        if isinstance(day, dict)
        for item in day.get("items", [])
        if isinstance(item, dict) and "title" in item
    }
    ensure(
        FAKE_AI_TITLE not in persisted_titles,
        "fake AI transport suggestion was unexpectedly persisted",
    )


def start_fake_ollama_process() -> subprocess.Popen[str]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "test" / "fake_ollama_host.py"),
        "--host",
        "0.0.0.0",
        "--port",
        "11434",
    ]
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    emit(f"started fake host Ollama test process pid={process.pid}")
    return process


def wait_for_fake_ollama_ready(process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    last_error = "no response yet"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr_output = ""
            if process.stderr is not None:
                stderr_output = process.stderr.read().strip()
            fail(
                "fake host Ollama process exited early with code "
                f"{process.returncode}: {stderr_output or 'no stderr output'}"
            )
        try:
            response = fetch_url(FAKE_OLLAMA_HOST_URL)
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(POLL_INTERVAL_SECONDS)
    fail(f"fake host Ollama did not become ready: {last_error}")


def stop_fake_ollama_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    emit(f"stopping fake host Ollama test process pid={process.pid}")
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def print_diagnostics(project_name: str, env_file: Path, phase_name: str) -> None:
    emit(
        f"{phase_name} failed; printing concise docker compose diagnostics for "
        "smoke services."
    )
    ps_result = run_command(
        compose_command(project_name, env_file, "ps", "--all"),
        check=False,
    )
    if ps_result.stdout.strip():
        print(ps_result.stdout.strip(), flush=True)
    if ps_result.stderr.strip():
        print(ps_result.stderr.strip(), flush=True)

    logs_result = run_command(
        compose_command(
            project_name,
            env_file,
            "logs",
            "--no-color",
            "--tail",
            "80",
            *SMOKE_SERVICES,
        ),
        check=False,
    )
    if logs_result.stdout.strip():
        print(logs_result.stdout.strip(), flush=True)
    if logs_result.stderr.strip():
        print(logs_result.stderr.strip(), flush=True)


def cleanup_compose_project(project_name: str, env_file: Path) -> None:
    run_command(
        compose_command(
            project_name,
            env_file,
            "down",
            "--volumes",
            "--remove-orphans",
        ),
        check=False,
    )


def run_phase(
    project_name: str,
    base_env_file: Path,
    phase: PhaseConfig,
) -> dict[str, Any]:
    emit(f"starting phase {phase.name}: {phase.description}")
    env_file = write_phase_env_file(
        base_env_file,
        project_name=project_name,
        phase=phase,
    )
    fake_process: subprocess.Popen[str] | None = None
    try:
        cleanup_compose_project(project_name, env_file)
        if phase.start_fake_ollama:
            fake_process = start_fake_ollama_process()
            wait_for_fake_ollama_ready(fake_process)

        run_command(
            compose_command(
                project_name,
                env_file,
                "up",
                "-d",
                *SMOKE_SERVICES,
            )
        )

        wait_for_shared_ui()
        wait_for_database_health(project_name, env_file)
        wait_for_backend_ready(project_name, env_file)
        wait_for_frontend_ready()
        verify_port_exposure(project_name, env_file)
        seeded_summary = verify_portal_and_seeded_frontend(project_name, env_file)
        health_summary = verify_phase_health(
            project_name,
            env_file,
            phase=phase,
        )

        if phase.name == "degraded-unavailable":
            verify_degraded_ai_behaviour(project_name, env_file)
            crud_summary = verify_crud_via_frontend(project_name, env_file)
        elif phase.name == "fake-ollama-transport":
            verify_ai_transport_success(project_name, env_file)
            crud_summary = {}
        else:
            crud_summary = {}

        summary = {
            "phase": phase.name,
            "first_seeded_trip": seeded_summary["first_trip_id"],
            "seeded_item_title": seeded_summary["seeded_item_title"],
            "database_status": health_summary["database_status"],
            "backend_ready_status": health_summary["backend_ready_status"],
            "backend_health_status": health_summary["backend_health_status"],
            "ai_health_status": health_summary["ai_health_status"],
            "ai_ready_http": health_summary["ai_ready_http"],
            **crud_summary,
        }
        emit(f"phase {phase.name} passed")
        return summary
    except SmokeError:
        print_diagnostics(project_name, env_file, phase.name)
        raise
    finally:
        cleanup_compose_project(project_name, env_file)
        stop_fake_ollama_process(fake_process)
        env_file.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    project_name = make_project_name(args.project_name)
    base_env_file = Path(args.env_file)
    selected_phase_names = args.phase or list(ROUTINE_PHASES)
    selected_phases = [PHASES[name] for name in selected_phase_names]

    ensure(base_env_file.exists(), f"base env file does not exist: {base_env_file}")
    ensure(COMPOSE_FILE.exists(), f"Compose file does not exist: {COMPOSE_FILE}")

    results = [
        run_phase(project_name, base_env_file, phase) for phase in selected_phases
    ]
    emit("completed all requested smoke phases")
    print(
        json.dumps(
            {
                "project_name": project_name,
                "phases": results,
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
