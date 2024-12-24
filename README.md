# AWS Spotter: EC2 Spot Price Tracker API

A REST API service that provides real-time and historical AWS EC2 spot instance prices across all regions. Features Redis caching for improved performance and reduced AWS API calls.

## Features

- RESTful API endpoints for spot price queries
- Redis caching with configurable expiration and locking mechanism
- Support for all EC2 instance types
- Cross-region price comparison
- Latest price and historical price data
- Automatic price updates via background service
- Detailed availability zone information
- Comprehensive error handling and instance availability checks
- Health monitoring endpoints
- Detailed logging with configurable levels

## Prerequisites

- Python 3.11+
- AWS account with EC2 spot price data access permissions
- Redis server (local or remote)
- Docker and Docker Compose (optional)

## Quick Start with Docker

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd aws-spot-price-comparison
   ```

2. Copy the example environment file:
   ```bash
   cp docker/docker-redis/.env.example docker/docker-redis/.env
   ```

3. Edit the `.env` file with your credentials and settings

4. Start the service with Docker Compose:
   ```bash
   cd docker/docker-redis
   docker-compose up -d
   ```

5. Check the service health:
   ```bash
   curl http://localhost:5001/health
   ```

## Manual Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd aws-spot-price-comparison
   ```

2. Install required packages:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy and configure environment variables:
   ```bash
   cp docker/docker-redis/.env.example .env
   # Edit .env with your settings
   ```

4. Start the API server:
   ```bash
   python api.py
   ```

## Configuration

The following environment variables can be configured:

| Variable | Description | Default |
|----------|-------------|---------|
| AWS_ACCESS_KEY_ID | AWS access key | Required |
| AWS_SECRET_ACCESS_KEY | AWS secret key | Required |
| AWS_DEFAULT_REGION | Default AWS region | us-east-1 |
| REDIS_HOST | Redis server host | redis |
| REDIS_PORT | Redis server port | 6379 |
| REDIS_PASSWORD | Redis password | Required |
| UPDATE_INTERVAL | Cache update interval (seconds) | 300 |
| CACHE_EXPIRY | Cache expiry time (seconds) | 600 |
| LOG_LEVEL | Logging level | INFO |
| INSTANCE_TYPES | Comma-separated list of instances to monitor | t2.micro,t3.micro |
| API_PORT | API server port | 5001 |
| API_HOST | API server host | 0.0.0.0 |

## API Endpoints

### 1. Get Latest Spot Price
```bash
GET /spot-prices/<region>/<instance_type>
```
Returns the latest spot price for a specific instance type in a region.

Response format:
```json
{
  "availability_zone": "ap-south-2b",
  "instance_type": "c5.2xlarge",
  "price": 0.07,
  "region": "ap-south-2",
  "source": "cache|aws",
  "price_timestamp": "2024-12-23T20:45:55+00:00",  // When AWS reported this price
  "cached_at": "2024-12-24T00:15:30+00:00"         // When we cached it
}
```

### 2. Get Best Price
```bash
GET /spot-prices/best/<instance_type>
```
Returns the lowest spot price across all regions for an instance type.

Example:
```bash
curl http://localhost:5001/spot-prices/best/t2.micro
```

Response:
```json
{
  "instance_type": "t2.micro",
  "best_price": 0.0035,
  "region": "us-east-1",
  "availability_zone": "us-east-1b",
  "timestamp": "2024-12-23T06:02:01+00:00",
  "source": "cache"
}
```

### 3. Health Check
```bash
GET /health
```
Returns the health status of the service and its dependencies.

Example:
```bash
curl http://localhost:5001/health
```

Response:
```json
{
  "status": "healthy",
  "timestamp": "2024-12-23T06:02:01+00:00",
  "services": {
    "redis": {
      "status": "healthy",
      "host": "redis",
      "port": 6379
    },
    "aws": {
      "status": "healthy",
      "region": "us-east-1",
      "regions_available": 25
    }
  }
}
```

## Error Handling

The API returns appropriate HTTP status codes and error messages:

- 200: Successful request
- 404: Price not found or instance type not available
- 500: Internal server error
- 503: Service unhealthy (Redis or AWS unavailable)

Error responses include detailed messages to help diagnose issues:

```json
{
  "error": "Instance type t99.micro is not offered in region us-east-1"
}
```

## Caching Behavior

- Fresh prices are cached for 10 minutes by default (configurable)
- Stale prices are returned if AWS API calls fail
- Cache status is indicated in responses via 'source' field
- TTL information is included when available

## Docker Support

The service includes:
- Multi-stage build for minimal image size
- Health checks for both API and Redis services
- Automatic container restart
- Volume mounting for AWS credentials
- Configurable through environment variables

## License

This project is licensed under the MIT License - see the LICENSE file for details.