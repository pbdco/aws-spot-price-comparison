import redis
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Any, Callable
import time
from functools import wraps
import os

class RedisCache:
    """Redis cache implementation with retries and error handling."""
    
    def __init__(self, host: str = 'localhost', port: int = 6379, password: str = None,
                 max_retries: int = 3, retry_delay: float = 0.1):
        """Initialize Redis cache with connection parameters."""
        self.host = host
        self.port = port
        self.password = password
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.cache_expiry = int(os.environ.get('CACHE_EXPIRY', 600))  # 10 minutes
        self.client = None
        self.connect()

    def connect(self):
        """Connect to Redis."""
        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                password=self.password,
                decode_responses=True,  # This ensures we get strings back
                socket_timeout=5,
                retry_on_timeout=True
            )
            logging.info(f"Connected to Redis at {self.host}:{self.port}")
        except Exception as e:
            logging.error(f"Failed to connect to Redis: {e}")
            raise

    def _retry_operation(self, operation, *args, **kwargs):
        """Retry Redis operation with reconnection."""
        try:
            return operation(*args, **kwargs)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            logging.warning(f"Redis operation failed, attempting reconnect: {e}")
            self.connect()
            return operation(*args, **kwargs)

    def _get_cache_key(self, region: str, instance_type: str) -> str:
        """Generate cache key for spot price data."""
        return f"spot_price:{region}:{instance_type}"

    def get_spot_prices(self, region: str, instance_type: str) -> Optional[Dict]:
        """Get cached spot price data."""
        try:
            key = self._get_cache_key(region, instance_type)
            data = self._retry_operation(self.client.get, key)
            
            if not data:
                return None
                
            return json.loads(data)
            
        except Exception as e:
            logging.error(f"Error getting price from cache for {instance_type} in {region}: {e}")
            return None

    def set_spot_prices(self, region: str, instance_type: str, data: Dict) -> bool:
        """Cache spot price data with expiry."""
        try:
            if not isinstance(data, dict) or 'prices' not in data:
                raise ValueError("Invalid price data format")

            key = self._get_cache_key(region, instance_type)
            
            self._retry_operation(
                self.client.setex,
                key,
                self.cache_expiry,
                json.dumps(data)
            )
            
            return True
            
        except Exception as e:
            logging.error(f"Error setting price in cache for {instance_type} in {region}: {e}")
            return False

    def set(self, key: str, value: str, ex: int = None, nx: bool = False) -> bool:
        """Set a value in Redis with optional expiry and NX flag."""
        try:
            return self._retry_operation(self.client.set, key, value, ex=ex, nx=nx)
        except Exception as e:
            logging.error(f"Redis set error: {e}")
            return False

    def get(self, key: str) -> Optional[str]:
        """Get a value from Redis."""
        try:
            return self._retry_operation(self.client.get, key)
        except Exception as e:
            logging.error(f"Redis get error: {e}")
            return None

    def clear_cache(self, pattern: str = "spot_price:*") -> bool:
        """Clear all cached data matching pattern."""
        try:
            cursor = 0
            while True:
                cursor, keys = self._retry_operation(
                    self.client.scan,
                    cursor,
                    match=pattern,
                    count=100
                )
                
                if keys:
                    self._retry_operation(self.client.delete, *keys)
                    
                if cursor == 0:
                    break
                    
            return True
            
        except Exception as e:
            logging.error(f"Error clearing cache with pattern {pattern}: {e}")
            return False
