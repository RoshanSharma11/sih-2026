FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SKYGUARD_API=http://127.0.0.1:8000 \
    SKYGUARD_DB=/var/lib/skyguard/skyguard.db

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[ui]" \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY frontend ./frontend
COPY data/processed ./data/processed
COPY v2-deliverable ./v2-deliverable
COPY scripts/serve.sh ./scripts/serve.sh

RUN chmod +x scripts/serve.sh \
    && mkdir -p /var/lib/skyguard

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

CMD ["./scripts/serve.sh"]
