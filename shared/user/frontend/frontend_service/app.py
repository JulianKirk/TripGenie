"""The account webpage -- sign in, sign up, and the account itself.

The backend service speaks JSON and a browser posts forms, so this service is
what turns one into the other. See ../../docs/backend-service-api.md for the
contract this consumes and ../../docs/frontend-service.md for the pages.

ponytail: no session. A successful login redirects to /account/{id} and the id
in the URL is the whole of "who is signed in" -- anyone holding that URL is
that user. Deliberate for this release (see the ponytail note on the backend's
login route); when it grows a real session, this is the module that sets the
cookie.

ponytail: no pydantic mirror of the user message, no client module. The decoded
JSON goes straight into the templates. Add models here when this service starts
computing on the data rather than displaying it.

ponytail: only the account edit is HTMX. Sign in, sign up and delete are plain
form posts that redirect -- a redirect through HTMX needs an HX-Redirect header
and buys nothing when the whole page changes anyway.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

import httpx
from fastapi import APIRouter, FastAPI, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from frontend_service.config import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))

PATH = "/users"
UNREACHABLE = "The account service is not responding. Try again shortly."


class BackendError(Exception):
    """The backend could not answer. Carries what to show the user."""


async def call(request: Request, method: str, path: str, **kwargs: Any) -> Any:
    """The decoded backend response, or a `BackendError` with a message fit to
    put on the page. The backend's error bodies are `{"detail": ...}`."""
    try:
        response = await request.app.state.backend.request(method, path, **kwargs)
    except httpx.RequestError as exc:
        raise BackendError(UNREACHABLE) from exc
    if response.is_success:
        # 204 is the answer to a DELETE and has no body to decode.
        if response.status_code == status.HTTP_204_NO_CONTENT:
            return None
        return response.json()
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    raise BackendError(str(detail) if detail else UNREACHABLE)


def render(request: Request, template: str, context: dict[str, Any]):
    return TEMPLATES.TemplateResponse(request, template, context)


def see_other(url: str) -> RedirectResponse:
    """303, not FastAPI's default 307: the browser has just posted a form, and
    what it should do next is GET the page it landed on."""
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Reports this service and the backend behind it, the same way the backend
    reports the database service."""
    try:
        body = await call(request, "GET", "/health")
    except BackendError:
        backend_status = "unreachable"
    else:
        backend_status = str(body.get("status", "unknown"))
    return {
        "status": "ok" if backend_status == "ok" else "degraded",
        "service": request.app.state.settings.service_name,
        "backend": backend_status,
    }


@router.get("/")
async def index(request: Request):
    """Both forms, no state. Nothing is fetched -- there is nothing to fetch
    until someone types."""
    return render(request, "login.html", {})


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    body = {"username": username, "password": password}
    try:
        user = await call(request, "POST", f"{PATH}/login", json=body)
    except BackendError as exc:
        # The username comes back so the user does not retype it; the password
        # deliberately does not.
        return render(
            request,
            "login.html",
            {"error": str(exc), "username": username},
        )
    return see_other(f"/account/{user['id']}")


@router.post("/signup")
async def signup(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    body = {"username": username, "password": password}
    try:
        user = await call(request, "POST", PATH, json=body)
    except BackendError as exc:
        return render(
            request,
            "login.html",
            {"signup_error": str(exc), "signup_username": username},
        )
    return see_other(f"/account/{user['id']}")


@router.get("/account/{user_id:uuid}")
async def account(request: Request, user_id: UUID):
    """The account page. A stale or made-up id lands back on the login page
    rather than showing an error for an account that is not there."""
    try:
        user = await call(request, "GET", f"{PATH}/{user_id}")
    except BackendError:
        return see_other("/")
    return render(request, "account.html", {"user": user})


@router.post("/account/{user_id:uuid}")
async def update_account(
    request: Request,
    user_id: UUID,
    username: str = Form(""),
    password: str = Form(""),
):
    """The only HTMX route: swaps the edit form back in with the result.

    Blank inputs are dropped rather than sent -- an empty password box means
    "leave it alone", not "set my password to the empty string".
    """
    body = {
        field: value.strip()
        for field, value in (("username", username), ("password", password))
        if value.strip()
    }
    if not body:
        return _form(request, user_id, username, error="Nothing to change.")
    try:
        user = await call(request, "PUT", f"{PATH}/{user_id}", json=body)
    except BackendError as exc:
        return _form(request, user_id, username, error=str(exc))
    return _form(request, user_id, user["username"], saved=True)


@router.post("/account/{user_id:uuid}/delete")
async def delete_account(request: Request, user_id: UUID):
    """Gone means gone -- back to the login page, with nothing to return to."""
    try:
        await call(request, "DELETE", f"{PATH}/{user_id}")
    except BackendError as exc:
        user = {"id": user_id, "username": ""}
        return render(request, "account.html", {"user": user, "error": str(exc)})
    return see_other("/")


def _form(
    request: Request,
    user_id: UUID,
    username: str,
    *,
    error: str = "",
    saved: bool = False,
):
    """The account edit form on its own -- what every save swaps into #account.

    The username shown comes from the backend's response on a save, never from
    the request, so the page cannot claim a change the backend did not store.
    """
    return render(
        request,
        "partials/account_form.html",
        {
            "user": {"id": user_id, "username": username},
            "error": error,
            "saved": saved,
        },
    )


def create_app(settings: Settings | None = None, *, transport: Any = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # `transport` is the same test seam the other two services use.
        backend = httpx.AsyncClient(
            base_url=settings.backend_url,
            timeout=settings.backend_timeout,
            transport=transport,
        )
        app.state.settings = settings
        app.state.backend = backend
        yield
        await backend.aclose()

    app = FastAPI(title="User Frontend Service", lifespan=lifespan)
    app.mount(
        "/static", StaticFiles(directory=str(PACKAGE_ROOT / "static")), name="static"
    )
    app.include_router(router)
    return app


app = create_app()
