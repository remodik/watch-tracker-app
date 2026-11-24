FROM python:3.12.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/watch-tracker
COPY requirements.txt .
RUN --mount=type=secret,id=pip_ca \
    if [ -r /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi; \
    pip install --no-cache-dir -r requirements.txt \
    && useradd --system --uid 10001 watchtracker \
    && chown watchtracker /srv/watch-tracker
COPY --chown=watchtracker app/ app/
COPY --chown=watchtracker migrations/ migrations/
COPY --chown=watchtracker static/ static/
COPY --chown=watchtracker alembic.ini main.py import_data.py ./
USER watchtracker
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]
