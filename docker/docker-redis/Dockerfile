FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create non-root user and setup AWS credentials directory
RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN mkdir -p /home/appuser/.aws && chown -R appuser:appuser /home/appuser
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Default command (will be overridden by docker-compose)
CMD ["python", "api.py"]
