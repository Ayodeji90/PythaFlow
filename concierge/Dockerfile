FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv

# Install dependencies first (cached layer) — package=false means uv installs
# the deps into .venv without trying to build the app itself.
COPY pyproject.toml ./
RUN uv sync --no-dev

COPY app ./app
COPY scripts ./scripts

EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
