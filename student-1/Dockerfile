# All three student-1 services in one image, mirroring student-2/Dockerfile.
# The split images under database/, backend/ and frontend/ are still what
# docker-compose builds; this is the single-container option.
FROM python:3.11-slim

# Each service reads its own variable name, so unlike student-2 there is no
# collision to work around: the three URLs can live in ENV and point at
# loopback, because in this image the three processes really are one host.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STUDENT1_SQLITE_PATH=/data/student-1/tripgenie.db \
    STUDENT1_BACKEND_API_PREFIX=/api \
    STUDENT1_BACKEND_DB_API_BASE_URL=http://127.0.0.1:8002 \
    STUDENT1_BACKEND_DB_API_PREFIX=/internal \
    STUDENT1_BACKEND_DB_API_TIMEOUT_SECONDS=5 \
    STUDENT1_FRONTEND_BACKEND_BASE_URL=http://127.0.0.1:8001 \
    STUDENT1_FRONTEND_BACKEND_API_PREFIX=/api

WORKDIR /app

RUN addgroup --system tripgenie \
    && adduser --system --ingroup tripgenie --home /nonexistent tripgenie \
    && mkdir -p /data/student-1

COPY database ./database
COPY backend ./backend
COPY frontend ./frontend

RUN python -m pip install --upgrade pip \
    && python -m pip install ./database ./backend ./frontend

RUN chown -R tripgenie:tripgenie /app /data

EXPOSE 8081

USER tripgenie

# ponytail: bash job control, not a supervisor -- `wait -n` kills the container
# when any one service exits, and compose restarts it. Add supervisord/s6 only
# if a single service needs to restart on its own.
CMD ["bash", "-c", "\
uvicorn database_service.app:app --host 0.0.0.0 --port 8002 & \
uvicorn backend_service.app:app --host 0.0.0.0 --port 8001 & \
uvicorn frontend_service.app:app --host 0.0.0.0 --port 8081 & \
wait -n"]
