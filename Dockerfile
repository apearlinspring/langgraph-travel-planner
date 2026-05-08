FROM python:3.12-slim

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=pypi.org

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install \
        --no-cache-dir \
        --disable-pip-version-check \
        --retries 10 \
        --timeout 120 \
        --index-url ${PIP_INDEX_URL} \
        --trusted-host ${PIP_TRUSTED_HOST} \
        -r /tmp/requirements.txt && \
    rm -f /tmp/requirements.txt

RUN /opt/venv/bin/pip install \
    --no-cache-dir \
    --disable-pip-version-check \
    --retries 10 \
    --timeout 120 \
    --index-url ${PIP_INDEX_URL} \
    --trusted-host ${PIP_TRUSTED_HOST} \
    langchain-core==1.2.31 \
    langchain-openai==1.1.7 \
    langgraph-prebuilt==1.0.5 \
    uv==0.10.11

RUN /opt/venv/bin/python -c "import importlib, importlib.metadata as md; assert md.version('aigohotel-mcp') == '0.3.1'; importlib.import_module('aigohotel_mcp.server')"

COPY app /app/app
COPY scripts /app/scripts
COPY data /app/data
COPY frontend /app/frontend

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV APP_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${APP_PORT}/health/live || exit 1

CMD ["python", "-m", "app.run"]
