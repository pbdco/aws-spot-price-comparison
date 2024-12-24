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

# Upgrade pip and setuptools first, before any other package
RUN pip install --no-cache-dir pip>=23.3.2 && \
    pip install --no-cache-dir setuptools>=70.0.0 wheel>=0.42.0 && \
    pip list | grep setuptools

# Copy requirements file
COPY requirements.txt .

# Remove setuptools from requirements.txt if present
RUN sed -i '/setuptools/d' requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Verify setuptools version
RUN pip list | grep setuptools

# Run the application
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "4", "api:app"]
