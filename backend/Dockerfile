FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints.txt ./

# CPU torch first to keep image smaller than CUDA wheels. Pinned so a rebuild
# reproduces the environment the published benchmarks ran in.
RUN pip install --upgrade pip \
    && pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt -c constraints.txt \
    && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# NLI faithfulness model (ADR-045), pinned to a commit so the container runs
# offline. Must match NLI_MODEL_ID / NLI_MODEL_REVISION in
# app/services/judges/faithfulness_nli.py (a test checks this).
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/nli-deberta-v3-small', revision='fa2804872c3b4bd748f38c0185cc85775361e735')"

COPY . .

EXPOSE 8000

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
# UVICORN_WORKERS (default 1) is expanded by docker-entrypoint.sh. With >1
# worker the in-memory metrics/rate limiter are per-process; the durable
# telemetry store (Postgres) is shared. See docs/observability.md.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "${UVICORN_WORKERS}"]
