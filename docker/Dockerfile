FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Set environment variables
ENV DOCKER_CONTAINER=1
ENV PYTHONUNBUFFERED=1
ENV API_PORT=5001
ENV API_HOST=0.0.0.0

# Create entrypoint script with gunicorn
RUN echo '#!/bin/sh\ngunicorn --bind ${API_HOST}:${API_PORT} --workers 4 --timeout 120 --access-logfile - --error-logfile - api:app' > /entrypoint.sh && \
    chmod +x /entrypoint.sh

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5001/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
