# Production Dockerfile for Return & Refund Chaser
# Self-contained: serves both FastAPI API and pre-compiled React frontend
FROM python:3.12-slim

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Install system dependencies if required (sqlite3, curl for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Ensure data directory exists
RUN mkdir -p /app/data

# Expose default HTTP port
EXPOSE 8000

# Healthcheck to verify the server is responding
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Start the unified backend and frontend server
CMD ["sh", "-c", "python main.py --server --host 0.0.0.0 --port ${PORT:-8000}"]
