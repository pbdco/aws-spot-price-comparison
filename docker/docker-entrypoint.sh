#!/bin/bash

# Check if AWS credentials are provided via environment variables
if [ -n "$AWS_ACCESS_KEY_ID" ] && [ -n "$AWS_SECRET_ACCESS_KEY" ]; then
    echo "Using AWS credentials from environment variables"
elif [ -d "/root/.aws" ]; then
    echo "Using AWS credentials from mounted config directory"
else
    echo "Warning: No AWS credentials found. Please provide credentials via environment variables or mount ~/.aws directory"
    echo "Example with environment variables:"
    echo "  docker run --rm \\"
    echo "    -e AWS_ACCESS_KEY_ID=your_key \\"
    echo "    -e AWS_SECRET_ACCESS_KEY=your_secret \\"
    echo "    pbdco/aws-spotter [options]"
    echo ""
    echo "Example with config file:"
    echo "  docker run --rm \\"
    echo "    -v ~/.aws:/root/.aws:ro \\"
    echo "    pbdco/aws-spotter [options]"
    exit 1
fi

# Execute the Python script with all arguments passed to the container
exec python /app/aws_spotter.py "$@"
