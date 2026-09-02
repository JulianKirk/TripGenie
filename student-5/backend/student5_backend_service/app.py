from __future__ import annotations

from fastapi import FastAPI

from .config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="TripGenie Student 5 Backend")

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"data": {"status": "healthy", "service": settings.service_name}}

    @app.get("/ready")
    def ready() -> dict[str, object]:
        return {"data": {"status": "ready", "service": settings.service_name}}

    return app


app = create_app()