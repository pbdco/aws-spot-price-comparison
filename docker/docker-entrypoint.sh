#!/bin/bash
set -e

# Check if --json flag is present in arguments
is_json=false
for arg in "$@"; do
    if [ "$arg" = "--json" ]; then
        is_json=true
        break
    fi
done

# Check if AWS credentials are provided via environment variables
if [[ -n "$AWS_ACCESS_KEY_ID" && -n "$AWS_SECRET_ACCESS_KEY" ]]; then
    if ! $is_json; then
        echo "Using AWS credentials from environment variables"
    fi
elif [[ -d "/root/.aws" ]]; then
    if ! $is_json; then
        echo "Using AWS credentials from mounted config directory"
    fi
else
    echo "Error: No AWS credentials found. Please provide credentials via environment variables or mount ~/.aws directory"
    exit 1
fi

# Always append --no-graph to the command arguments
exec python /app/aws_spotter.py --no-graph "$@"
