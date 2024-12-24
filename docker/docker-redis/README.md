# Redis Cache for Spot Prices

Redis configuration for caching AWS spot instance prices.

## Configuration

### AWS Authentication

The service supports two authentication methods:

1. **AWS SSO**:
   ```env
   # .env
   AWS_PROFILE=your_sso_profile
   AWS_DEFAULT_REGION=ap-south-1
   ```
   Make sure to run `aws sso login` before starting the service.

2. **Static Credentials**:
   ```env
   # .env
   AWS_ACCESS_KEY_ID=your_access_key
   AWS_SECRET_ACCESS_KEY=your_secret_key
   AWS_DEFAULT_REGION=ap-south-1
   ```

### Redis Settings
- Memory limit: 100MB
- Eviction policy: LRU (Least Recently Used)
- Persistence: Save every 60 seconds if at least 1 key changed
- No append-only file
- Cache TTL: 1 hour
- Cache validity: 30 minutes

## Usage

1. Copy and configure environment:
   ```bash
   cp .env.example .env
   # Edit .env with your AWS credentials or SSO profile
   ```

2. Start services:
   ```bash
   docker-compose up -d
   ```

3. Check status:
   ```bash
   docker-compose ps
   ```

## Monitoring

Check cache status:
```bash
docker-compose exec redis redis-cli info stats
```

List cached prices:
```bash
docker-compose exec redis redis-cli keys "spot_prices:*"
```

## Cache Structure

Keys format:
```
spot_prices:{region}:{instance_type}
```

Value format:
```json
{
  "price": 0.0016,
  "timestamp": 1703334183
}
