FROM python:3.11-slim

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Shared SQLite lives here; mounted as a volume in docker-compose.
RUN mkdir -p /app/data
ENV PYTHONUNBUFFERED=1

# Default command is overridden per-service in docker-compose.yml.
CMD ["python", "-m", "src.orchestrator", "loop"]
