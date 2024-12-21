FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the script and entrypoint
COPY aws_spotter.py .
COPY docker/docker-entrypoint.sh docker-entrypoint.sh

# Make scripts executable
RUN chmod +x aws_spotter.py docker-entrypoint.sh

# Set the entrypoint to our wrapper script
ENTRYPOINT ["/app/docker-entrypoint.sh"]
