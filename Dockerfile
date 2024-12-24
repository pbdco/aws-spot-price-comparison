# Use Python 3.11 slim as base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Force remove any existing setuptools
RUN pip uninstall -y setuptools && \
    pip install --no-cache-dir pip>=23.3.2 && \
    pip install --no-cache-dir setuptools==70.0.0 && \
    pip install --no-cache-dir wheel>=0.42.0 && \
    pip freeze | grep setuptools

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies with --no-deps first
RUN pip install --no-cache-dir --no-deps -r requirements.txt && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir setuptools==70.0.0 && \
    pip freeze | grep setuptools

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Final verification of setuptools version
RUN pip freeze | grep setuptools && \
    if [ "$(pip freeze | grep setuptools | cut -d'=' -f3)" != "70.0.0" ]; then \
    echo "Wrong setuptools version!" && exit 1; \
    fi

# Run the application
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "4", "api:app"]
