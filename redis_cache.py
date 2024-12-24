import redis
import json
import logging
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable
import time
import os

class ConsistentHash:
    """Consistent hashing implementation for region distribution."""
    
    def __init__(self, nodes: List[str], replicas: int = 100):
        self.replicas = replicas
        self.ring = {}
        self.sorted_keys = []

        for node in nodes:
            self.add_node(node)

    def add_node(self, node: str):
        """Add a node to the hash ring."""
        for i in range(self.replicas):
            key = self._hash(f"{node}:{i}")
            self.ring[key] = node
            self.sorted_keys.append(key)
        self.sorted_keys.sort()

    def remove_node(self, node: str):
        """Remove a node from the hash ring."""
        for i in range(self.replicas):
            key = self._hash(f"{node}:{i}")
            del self.ring[key]
            self.sorted_keys.remove(key)

    def get_node(self, key: str) -> str:
        """Get the node responsible for the given key."""
        if not self.ring:
            raise Exception("Hash ring is empty")
        
        hash_key = self._hash(key)
        
        # Find the first point in the ring after hash_key
        for ring_key in self.sorted_keys:
            if ring_key >= hash_key:
                return self.ring[ring_key]
        
        # If we reached the end, return the first node
        return self.ring[self.sorted_keys[0]]

    def _hash(self, key: str) -> int:
        """Generate hash for a key."""
        return int(hashlib.md5(key.encode()).hexdigest(), 16)

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
                retry_on_timeout=True,
                health_check_interval=30  # Add periodic health checks
            )
            # Test connection
            self.client.ping()
            logging.info(f"Connected to Redis at {self.host}:{self.port}")
        except Exception as e:
            logging.error(f"Failed to connect to Redis: {e}")
            raise

    def _retry_operation(self, operation, *args, **kwargs):
        """Retry Redis operation with reconnection."""
        max_retries = 3
        retry_delay = 1
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return operation(*args, **kwargs)
            except (redis.ConnectionError, redis.TimeoutError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    logging.warning(f"Redis operation failed (attempt {attempt + 1}/{max_retries}): {e}")
                    time.sleep(retry_delay * (attempt + 1))
                    self.connect()  # Try to reconnect
            except Exception as e:
                logging.error(f"Unexpected Redis error: {e}")
                raise
        
        logging.error(f"Redis operation failed after {max_retries} attempts: {last_error}")
        raise last_error

    def _get_cache_key(self, region: str, instance_type: str) -> str:
        """Generate cache key for spot price data."""
        return f"spot_price:{region}:{instance_type}"

    def get_spot_prices(self, region: str, instance_type: str) -> Optional[Dict]:
        """Get cached spot price data."""
        try:
            key = self._get_cache_key(region, instance_type)
            data = self._retry_operation(self.client.get, key)
            if data:
                try:
                    return json.loads(data)
                except json.JSONDecodeError as e:
                    logging.error(f"Error decoding cache data for {instance_type} in {region}: {e}")
                    return None
            return None
        except Exception as e:
            logging.error(f"Error getting spot prices from cache for {instance_type} in {region}: {e}")
            return None

    def set_spot_prices(self, region: str, instance_type: str, data: Dict) -> bool:
        """Cache spot price data with expiry."""
        try:
            key = self._get_cache_key(region, instance_type)
            # Add no_prices field if not present
            if 'no_prices' not in data:
                data['no_prices'] = False
            
            # Ensure prices is a dict
            if 'prices' not in data:
                data['prices'] = {}
                
            # Ensure timestamps are present
            now = datetime.now(timezone.utc).isoformat()
            if 'aws_timestamp' not in data:
                data['aws_timestamp'] = now
            if 'cached_at' not in data:
                data['cached_at'] = now
                
            return bool(self._retry_operation(
                self.client.set,
                key,
                json.dumps(data),
                ex=self.cache_expiry
            ))
            
        except Exception as e:
            logging.error(f"Error setting price in cache for {instance_type} in {region}: {e}")
            return False

    def delete_spot_prices(self, region: str, instance_type: str) -> bool:
        """Delete cached spot price data."""
        try:
            key = self._get_cache_key(region, instance_type)
            return bool(self._retry_operation(self.client.delete, key))
        except Exception as e:
            logging.error(f"Error deleting spot prices from cache for {instance_type} in {region}: {e}")
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

    def assign_worker_regions(self, worker_id: str, total_workers: int, regions: list) -> list:
        """Assign regions to a worker using round-robin distribution."""
        try:
            if not regions:
                return []

            # Sort regions for consistency
            sorted_regions = sorted(regions)
            
            # Normalize worker_id to be between 0 and total_workers-1
            worker_num = int(worker_id) % total_workers
            
            # Calculate expected regions per worker
            total_regions = len(sorted_regions)
            base_regions_per_worker = total_regions // total_workers
            extra_regions = total_regions % total_workers
            
            # Calculate start and end indices for this worker's regions
            start_idx = worker_num * base_regions_per_worker + min(worker_num, extra_regions)
            end_idx = start_idx + base_regions_per_worker + (1 if worker_num < extra_regions else 0)
            
            # Get assigned regions
            worker_regions = sorted_regions[start_idx:end_idx]
            
            # Log assignment details
            logging.info(f"Worker {worker_id} (normalized to {worker_num}) assigned {len(worker_regions)} regions: {worker_regions}")
            
            return worker_regions
        except Exception as e:
            logging.error(f"Error assigning regions to worker: {e}")
            return []

    def get_worker_count(self) -> int:
        """Get the total number of workers from environment."""
        try:
            return int(os.environ.get('GUNICORN_WORKERS', 4))
        except Exception as e:
            logging.error(f"Error getting worker count: {e}")
            return 4  # Default to 4 workers

    def register_worker(self, worker_id: str) -> bool:
        """Register a worker and set expiry."""
        try:
            self.client.sadd('active_workers', worker_id)
            self.client.expire('active_workers', 60)  # Expire after 60 seconds
            return True
        except Exception as e:
            logging.error(f"Error registering worker: {e}")
            return False

    def heartbeat(self, worker_id: str) -> bool:
        """Update worker heartbeat."""
        try:
            if self.client.sismember('active_workers', worker_id):
                self.client.expire('active_workers', 60)
                return True
            return False
        except Exception as e:
            logging.error(f"Error updating heartbeat: {e}")
            return False

    def set_regions(self, regions: List[str]) -> bool:
        """Cache list of AWS regions."""
        try:
            return self.set('aws_regions', json.dumps(regions), ex=3600)  # Cache for 1 hour
        except Exception as e:
            logging.error(f"Error caching regions: {e}")
            return False

    def get_regions(self) -> Optional[List[str]]:
        """Get cached list of AWS regions."""
        try:
            data = self.get('aws_regions')
            return json.loads(data) if data else None
        except Exception as e:
            logging.error(f"Error getting cached regions: {e}")
            return None

    def set_worker_best_price(self, instance_type: str, worker_id: str, price_data: dict) -> None:
        """Store a worker's best price result."""
        try:
            key = f"worker_best_price:{instance_type}:{worker_id}"
            self.client.setex(key, 60, json.dumps(price_data))  # Expire after 60 seconds
        except Exception as e:
            logging.error(f"Error setting worker best price: {e}")

    def get_all_worker_best_prices(self, instance_type: str) -> dict:
        """Get all workers' best prices for an instance type."""
        try:
            pattern = f"worker_best_price:{instance_type}:*"
            keys = self.client.keys(pattern)
            results = {}
            for key in keys:
                worker_id = key.decode().split(':')[-1]
                data = self.client.get(key)
                if data:
                    results[worker_id] = json.loads(data)
            return results
        except Exception as e:
            logging.error(f"Error getting all worker best prices: {e}")
            return {}

    def init_best_price_request(self, request_id: str, total_regions: int) -> None:
        """Initialize a best price request with a short TTL."""
        try:
            key = f"best_price_request:{request_id}"
            self.client.setex(key, 120, json.dumps({  # 2 minutes TTL
                'total_regions': total_regions,
                'results': []
            }))
        except Exception as e:
            logging.error(f"Error initializing best price request: {e}")

    def update_best_price_partial(self, request_id: str, price_data: dict) -> None:
        """Update partial results for a best price request."""
        try:
            key = f"best_price_request:{request_id}"
            pipe = self.client.pipeline()
            current = self.client.get(key)
            if current:
                data = json.loads(current)
                data['results'].append(price_data)
                pipe.setex(key, 120, json.dumps(data))  # 2 minutes TTL
                pipe.execute()
        except Exception as e:
            logging.error(f"Error updating best price partial result: {e}")

    def get_best_price_results(self, request_id: str) -> list:
        """Get all results for a best price request."""
        try:
            key = f"best_price_request:{request_id}"
            data = self.client.get(key)
            if data:
                return json.loads(data)['results']
            return []
        except Exception as e:
            logging.error(f"Error getting best price results: {e}")
            return []
