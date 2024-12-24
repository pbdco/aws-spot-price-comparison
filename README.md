# AWS Spotter: EC2 Spot Price Tracker API

A high-performance REST API service that provides real-time and historical AWS EC2 spot instance prices across all regions. Features Redis caching, distributed worker processing, and intelligent region assignment for optimal performance.

## Features

- **Distributed Processing**:
  - Multi-worker architecture with Gunicorn
  - Intelligent region assignment per worker
  - Parallel price fetching across 25 AWS regions
  - Optimized worker distribution for balanced load

- **Advanced Caching**:
  - Redis-based caching with configurable expiration
  - Distributed locking mechanism
  - Worker-specific cache management
  - Efficient cache invalidation

- **Comprehensive Price Tracking**:
  - Support for 22+ EC2 instance types
  - Cross-region price comparison
  - Real-time and historical price data
  - Detailed availability zone information
  - Best price finder across all regions

- **Monitoring and Logging**:
  - Health monitoring endpoints
  - Detailed worker-specific logging
  - Request tracing with worker IDs
  - Performance metrics tracking
  - Debug-level visibility into price updates

- **Error Handling**:
  - Comprehensive error management
  - Instance availability checks
  - Region-specific error reporting
  - Automatic retry mechanisms

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
| LOG_LEVEL | Logging level | DEBUG |
| INSTANCE_TYPES | Comma-separated list of instances to monitor | Multiple types* |
| API_PORT | API server port | 5001 |
| API_HOST | API server host | 0.0.0.0 |
| GUNICORN_WORKERS | Number of Gunicorn workers | 20 |

\* Default instance types include: t2.micro, t2.small, t2.medium, t3.micro, t3.small, t3.medium, c5.large, c5.xlarge, r5.large, r5.xlarge, p4d.24xlarge, x2gd.xlarge, inf1.xlarge, c6gn.xlarge, r6g.xlarge, m6g.xlarge, t4g.xlarge, g5.xlarge, trn1.2xlarge, vt1.3xlarge, dl1.24xlarge, hpc6a.48xlarge

## API Endpoints

### 1. Get Latest Spot Price
```bash
GET /spot-prices/<region>/<instance_type>
```
Returns the latest spot price for a specific instance type in a region.

### 2. Get Best Price
```bash
GET /best-price/<instance_type>
```
Returns the lowest spot price across all regions for a specific instance type.

### 3. Health Check
```bash
GET /health
```
Returns service health status and worker information.

## Response Format

### Spot Price Response
```json
{
    "instance_type": "t3.micro",
    "region": "us-east-1",
    "prices": {
        "us-east-1a": 0.0035,
        "us-east-1b": 0.0034,
        "us-east-1c": 0.0033
    },
    "source": "aws-api",
    "cached_at": "2024-12-24T02:51:15Z"
}
```

### Best Price Response
```json
{
    "instance_type": "t3.micro",
    "region": "us-east-1",
    "price": 0.0033,
    "availability_zone": "us-east-1c",
    "source": "aws-api",
    "cached_at": "2024-12-24T02:51:15Z"
}
```

## Worker Distribution

The service uses an intelligent worker distribution system:
- 20 Gunicorn workers process requests in parallel
- Workers are assigned specific AWS regions
- Even distribution of regions across workers (1-2 regions per worker)
- Covers all 25 AWS regions efficiently
- Worker-specific logging for easy debugging

## Performance Optimization

- Parallel processing of AWS regions
- Redis caching to minimize API calls
- Worker-specific region assignments
- Efficient cache invalidation
- Request distribution across workers

## Error Handling

The service includes comprehensive error handling:
- AWS API error management
- Cache miss handling
- Region availability checks
- Worker process monitoring
- Detailed error logging with worker context

## License

This project is licensed under the MIT License - see the LICENSE file for details.