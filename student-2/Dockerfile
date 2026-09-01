# All three student-2 services in one image, the way the other students ship a
# single container per service area. The split images under database/, backend/
# and frontend/ are still what docker-compose builds.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BACKEND_URL=http://127.0.0.1:9000 \
    BACKEND_TIMEOUT=5 \
    DB_TIMEOUT=5 \
    # Country and city live in the shared reference service, which is not in
    # this image -- there is one of it, not one per student. On the compose
    # network this name resolves; run the image alone and /health says
    # "location": "unreachable", with rows that cannot name their place.
    LOCATION_URL=http://shared-backend:9100 \
    SQLITE_URL=sqlite:////data/accommodation.db \
    DB_SERVICE_URL=http://127.0.0.1:9001

WORKDIR /app

RUN addgroup --system tripgenie \
    && adduser --system --ingroup tripgenie --home /nonexistent tripgenie \
    && mkdir -p /data

COPY database ./database
COPY backend ./backend
COPY frontend ./frontend

RUN python -m pip install --upgrade pip \
    && python -m pip install ./database ./backend ./frontend

RUN chown -R tripgenie:tripgenie /app /data

EXPOSE 9003

USER tripgenie

# The database and backend services both read DATABASE_URL, and mean different
# things by it, so each process gets its own value inline rather than from ENV.
# ponytail: bash job control, not a supervisor -- `wait -n` kills the container
# when any one service exits, and compose restarts it. Add supervisord/s6 only
# if a single service needs to restart on its own.
CMD ["bash", "-c", "\
DATABASE_URL=$SQLITE_URL uvicorn database_service.app:app --host 0.0.0.0 --port 9001 & \
DATABASE_URL=$DB_SERVICE_URL uvicorn backend_service.app:app --host 0.0.0.0 --port 9000 & \
uvicorn frontend_service.app:app --host 0.0.0.0 --port 9003 & \
wait -n"]
