import json
import time
from typing import Optional, Dict, Any
import redis
from redis.exceptions import RedisError


class RedisCache:
    def __init__(self, host: str = 'localhost', port: int = 6379, db: int = 0):
        self.redis_client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self.cache_ttl = 3600  # 1 hour TTL for cleanup
        self.max_age = 1800    # 30 minutes max age for valid cache

    def _get_key(self, region: str, instance_type: str) -> str:
        """Generate Redis key for spot price data."""
        return f"spot_prices:{region}:{instance_type}"

    def get_cached_price(self, region: str, instance_type: str) -> Optional[float]:
        """
        Get cached spot price if available and not expired.
        Returns None if cache miss or expired.
        """
        try:
            key = self._get_key(region, instance_type)
            cached_data = self.redis_client.get(key)
            
            if not cached_data:
                return None

            data = json.loads(cached_data)
            cached_time = data['timestamp']
            current_time = int(time.time())

            # Check if cache is still valid (less than 30 minutes old)
            if current_time - cached_time <= self.max_age:
                return float(data['price'])
            
            return None

        except (RedisError, json.JSONDecodeError, KeyError) as e:
            print(f"Cache error: {str(e)}")
            return None

    def set_price(self, region: str, instance_type: str, price: float) -> bool:
        """
        Cache spot price with current timestamp.
        Returns True if successful, False otherwise.
        """
        try:
            key = self._get_key(region, instance_type)
            data = {
                'price': price,
                'timestamp': int(time.time())
            }
            
            self.redis_client.setex(
                key,
                self.cache_ttl,
                json.dumps(data)
            )
            return True

        except RedisError as e:
            print(f"Cache error: {str(e)}")
            return False

    def clear_cache(self, region: str = None, instance_type: str = None) -> bool:
        """
        Clear cache for specific region/instance or all cache if none specified.
        """
        try:
            if region and instance_type:
                key = self._get_key(region, instance_type)
                self.redis_client.delete(key)
            else:
                # Clear all spot price cache
                pattern = "spot_prices:*"
                keys = self.redis_client.keys(pattern)
                if keys:
                    self.redis_client.delete(*keys)
            return True

        except RedisError as e:
            print(f"Cache error: {str(e)}")
            return False

    def is_connected(self) -> bool:
        """Check if Redis connection is alive."""
        try:
            return self.redis_client.ping()
        except RedisError:
            return False
