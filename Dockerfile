FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency files dulu (layer caching)
COPY pyproject.toml uv.lock ./

# Install dependencies tanpa dev dependencies
RUN uv sync --frozen --no-dev

# Copy source code
COPY . .

# Jalankan pakai uv
CMD ["uv", "run", "src/main.py"]
