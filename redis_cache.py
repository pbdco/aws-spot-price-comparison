import redis
import json
import logging
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union
import time
import os
import random

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

class TaskPriority:
    HIGH = 100  # API requests
    MEDIUM = 50  # Reserved for future use
    LOW = 10    # Scheduled updates

class TaskStatus:
    QUEUED = 'queued'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'
    PENDING = 'pending'

class RedisCache:
    """Redis cache implementation with priority queue system."""
    
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
                decode_responses=True,
                socket_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30
            )
            self.client.ping()
            logging.info(f"Connected to Redis at {self.host}:{self.port}")
        except Exception as e:
            logging.error(f"Failed to connect to Redis: {e}")
            raise

    def _retry_operation(self, operation: callable, *args, **kwargs) -> Any:
        """Retry Redis operation with reconnection."""
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                return operation(*args, **kwargs)
            except (redis.ConnectionError, redis.TimeoutError) as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    logging.warning(f"Redis operation failed (attempt {attempt + 1}/{self.max_retries}): {e}")
                    time.sleep(self.retry_delay * (attempt + 1))
                    try:
                        self.connect()
                    except Exception as e:
                        logging.error(f"Failed to reconnect to Redis: {e}")
            except Exception as e:
                logging.error(f"Unexpected Redis error: {e}")
                raise
        
        logging.error(f"Redis operation failed after {self.max_retries} attempts: {last_error}")
        raise last_error

    def enqueue_task(self, task_type: str, task_data: Dict, priority: TaskPriority = TaskPriority.LOW) -> str:
        """Enqueue a task with priority."""
        try:
            # Generate unique task ID
            timestamp = time.time()
            random_suffix = ''.join(random.choices('0123456789abcdef', k=8))
            task_id = f"{task_type}_{timestamp}_{random_suffix}"
            
            # Create task data
            task = {
                'type': task_type,
                'status': TaskStatus.PENDING,
                'data': json.dumps(task_data),
                'created_at': datetime.now(timezone.utc).isoformat(),
                'priority': priority
            }
            
            # Store task data
            task_key = f"task:{task_id}"
            self.client.hset(task_key, mapping=task)
            self.client.expire(task_key, self.cache_expiry)  # Set expiry
            
            # Add to appropriate queue
            queue_key = 'tasks:high' if priority == TaskPriority.HIGH else 'tasks:low'
            self.client.lpush(queue_key, task_id)
            
            logging.info(f"Enqueued task {task_id} with priority {priority}")
            return task_id
            
        except Exception as e:
            logging.error(f"Error enqueueing task: {e}")
            raise

    def get_next_task(self) -> Optional[Dict]:
        """Get the next task from the queue with priority."""
        try:
            # Try high priority queue first
            task_id = self.client.rpop('tasks:high')
            if not task_id:
                # Then try low priority queue
                task_id = self.client.rpop('tasks:low')
            
            if not task_id:
                return None
                
            task_id = task_id.decode()
            task_key = f"task:{task_id}"
            
            # Get task data
            task_data = self.client.hgetall(task_key)
            if not task_data:
                logging.warning(f"Task {task_id} not found in Redis")
                return None
                
            # Convert bytes to string and parse data
            task = {k.decode(): v.decode() for k, v in task_data.items()}
            task['task_id'] = task_id
            
            # Parse data field if present
            if 'data' in task:
                try:
                    task['data'] = json.loads(task['data'])
                except json.JSONDecodeError:
                    logging.error(f"Failed to parse data for task {task_id}")
                    task['data'] = {}
            
            # Update task status to processing
            self.client.hset(task_key, 'status', TaskStatus.PROCESSING)
            
            return task
            
        except Exception as e:
            logging.error(f"Error getting next task: {e}")
            return None

    def requeue_stale_tasks(self) -> int:
        """Requeue tasks that have been stuck in processing state."""
        try:
            stale_count = 0
            pattern = 'task:*'
            
            # Scan all task keys
            for task_key in self.client.scan_iter(match=pattern):
                task_data = self.client.hgetall(task_key)
                if not task_data:
                    continue
                
                # Convert bytes to string
                task = {k.decode(): v.decode() for k, v in task_data.items()}
                
                # Check if task is stuck in processing
                if task.get('status') == TaskStatus.PROCESSING:
                    created_at = datetime.fromisoformat(task['created_at'])
                    age = (datetime.now(timezone.utc) - created_at).total_seconds()
                    
                    # If task has been processing for more than 5 minutes, requeue it
                    if age > 300:  # 5 minutes
                        task_id = task_key.decode().split(':')[1]
                        priority = task.get('priority', TaskPriority.LOW)
                        queue_key = 'tasks:high' if priority == TaskPriority.HIGH else 'tasks:low'
                        
                        # Reset status and requeue
                        self.client.hset(task_key, 'status', TaskStatus.PENDING)
                        self.client.lpush(queue_key, task_id)
                        stale_count += 1
                        
                        logging.info(f"Requeued stale task {task_id}")
            
            return stale_count
            
        except Exception as e:
            logging.error(f"Error requeuing stale tasks: {e}")
            return 0

    def set_task_result(self, task_id: str, result: dict) -> None:
        """Set the result for a task."""
        try:
            task_key = f"task:{task_id}"
            result_key = f"result:{task_id}"
            
            # Store the result
            self.client.set(
                result_key,
                json.dumps(result),
                ex=self.cache_expiry
            )
            
            # Update task status
            task_data = {
                'status': TaskStatus.COMPLETED,
                'result_key': result_key,
                'completed_at': datetime.now(timezone.utc).isoformat()
            }
            self.client.hset(task_key, mapping=task_data)
            
            logging.debug(f"Set result for task {task_id}")
            
        except Exception as e:
            logging.error(f"Error setting task result: {e}")
            raise

    def set_task_error(self, task_id: str, error: str) -> None:
        """Set an error for a task."""
        try:
            task_key = f"task:{task_id}"
            
            # Update task status with error
            task_data = {
                'status': TaskStatus.FAILED,
                'error': error,
                'completed_at': datetime.now(timezone.utc).isoformat()
            }
            self.client.hset(task_key, mapping=task_data)
            
            logging.debug(f"Set error for task {task_id}: {error}")
            
        except Exception as e:
            logging.error(f"Error setting task error: {e}")
            raise

    def wait_for_task_result(self, task_id: str, timeout: int = 30) -> Optional[dict]:
        """Wait for a task result with timeout."""
        try:
            start_time = time.time()
            task_key = f"task:{task_id}"
            
            while (time.time() - start_time) < timeout:
                # Check task status
                task_data = self.client.hgetall(task_key)
                if not task_data:
                    time.sleep(0.1)
                    continue
                
                # Convert bytes to string for all fields
                task_data = {k.decode(): v.decode() for k, v in task_data.items()}
                status = task_data.get('status', '')
                
                if status == TaskStatus.COMPLETED:
                    # Get result from result key
                    result_key = task_data.get('result_key')
                    if not result_key:
                        raise Exception("Task completed but result key missing")
                        
                    result_json = self.client.get(result_key)
                    if result_json:
                        return json.loads(result_json)
                    raise Exception("Task result not found")
                    
                elif status == TaskStatus.FAILED:
                    error = task_data.get('error', 'Unknown error')
                    raise Exception(error)
                    
                time.sleep(0.1)
            
            raise TimeoutError("Task timed out")
            
        except Exception as e:
            logging.error(f"Error waiting for task result: {e}")
            raise

    def complete_task(self, task_id: str, result: Dict) -> bool:
        """Mark a task as completed with its result."""
        try:
            pipe = self.client.pipeline()
            
            # Get task details
            task_data = self._retry_operation(
                self.client.get,
                f"task:{task_id}"
            )
            
            if not task_data:
                return False
                
            task = json.loads(task_data)
            task['status'] = TaskStatus.COMPLETED
            task['result'] = result
            task['updated_at'] = datetime.now(timezone.utc).isoformat()
            
            # Update task and remove from processing set
            pipe.set(f"task:{task_id}", json.dumps(task), ex=3600)
            pipe.srem('processing_tasks', task_id)
            pipe.execute()
            
            return True
            
        except Exception as e:
            logging.error(f"Error completing task: {e}")
            return False

    def fail_task(self, task_id: str, error: str) -> bool:
        """Mark a task as failed with error details."""
        try:
            pipe = self.client.pipeline()
            
            # Get task details
            task_data = self._retry_operation(
                self.client.get,
                f"task:{task_id}"
            )
            
            if not task_data:
                return False
                
            task = json.loads(task_data)
            task['status'] = TaskStatus.FAILED
            task['error'] = error
            task['updated_at'] = datetime.now(timezone.utc).isoformat()
            
            # Update task and remove from processing set
            pipe.set(f"task:{task_id}", json.dumps(task), ex=3600)
            pipe.srem('processing_tasks', task_id)
            pipe.execute()
            
            return True
            
        except Exception as e:
            logging.error(f"Error failing task: {e}")
            return False

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Get the current status of a task."""
        try:
            task_data = self._retry_operation(
                self.client.get,
                f"task:{task_id}"
            )
            return json.loads(task_data) if task_data else None
        except Exception as e:
            logging.error(f"Error getting task status: {e}")
            return None

    def get_queue_metrics(self) -> Dict:
        """Get current queue metrics."""
        try:
            queued = self._retry_operation(
                self.client.zcard,
                'task_queue'
            )
            processing = self._retry_operation(
                self.client.scard,
                'processing_tasks'
            )
            
            return {
                'queued_tasks': queued,
                'processing_tasks': processing,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logging.error(f"Error getting queue metrics: {e}")
            return {
                'queued_tasks': 0,
                'processing_tasks': 0,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

    def get_spot_prices(self, region: str, instance_type: str) -> Optional[Dict]:
        """Get cached spot price data."""
        try:
            key = self._get_cache_key(region, instance_type)
            data = self._retry_operation(self.client.get, key)
            return json.loads(data) if data else None
        except Exception as e:
            logging.error(f"Error getting spot prices from cache: {e}")
            return None

    def set_spot_prices(self, region: str, instance_type: str, data: Dict) -> bool:
        """Cache spot price data with expiry."""
        try:
            key = self._get_cache_key(region, instance_type)
            return bool(self._retry_operation(
                self.client.setex,
                key,
                self.cache_expiry,
                json.dumps(data)
            ))
        except Exception as e:
            logging.error(f"Error setting spot prices in cache: {e}")
            return False

    def delete_spot_prices(self, region: str, instance_type: str) -> bool:
        """Delete cached spot price data."""
        try:
            key = self._get_cache_key(region, instance_type)
            return bool(self._retry_operation(self.client.delete, key))
        except Exception as e:
            logging.error(f"Error deleting spot prices from cache: {e}")
            return False

    def set(self, key: str, value: str, ex: int = None, nx: bool = False) -> bool:
        """Set a value in Redis with optional expiry and NX flag."""
        try:
            return bool(self._retry_operation(
                self.client.set,
                key,
                value,
                ex=ex,
                nx=nx
            ))
        except Exception as e:
            logging.error(f"Error setting value in Redis: {e}")
            return False

    def get(self, key: str) -> Optional[str]:
        """Get a value from Redis."""
        try:
            return self._retry_operation(self.client.get, key)
        except Exception as e:
            logging.error(f"Error getting value from Redis: {e}")
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

    def _get_cache_key(self, region: str, instance_type: str) -> str:
        """Generate cache key for spot price data."""
        return f"spot_price:{region}:{instance_type}"

    def get_regions(self) -> Optional[List[str]]:
        """Get cached list of AWS regions."""
        try:
            data = self.get('aws_regions')
            return json.loads(data) if data else None
        except Exception as e:
            logging.error(f"Error getting cached regions: {e}")
            return None

    def set_regions(self, regions: List[str]) -> bool:
        """Cache list of AWS regions."""
        try:
            return self.set('aws_regions', json.dumps(regions), ex=3600)  # Cache for 1 hour
        except Exception as e:
            logging.error(f"Error caching regions: {e}")
            return False

    def register_worker(self, worker_id: str) -> bool:
        """Register a worker and set expiry."""
        try:
            key = f"worker:{worker_id}"
            return self.set(key, 'active', ex=60)  # Expire after 60 seconds
        except Exception as e:
            logging.error(f"Error registering worker: {e}")
            return False

    def heartbeat(self, worker_id: str) -> bool:
        """Update worker heartbeat."""
        try:
            key = f"worker:{worker_id}"
            return self.set(key, 'active', ex=60)  # Reset expiry to 60 seconds
        except Exception as e:
            logging.error(f"Error updating heartbeat: {e}")
            return False

    def get_worker_count(self) -> int:
        """Get the total number of workers from environment."""
        try:
            return int(os.environ.get('GUNICORN_WORKERS', 4))
        except Exception as e:
            logging.error(f"Error getting worker count: {e}")
            return 4  # Default to 4 workers
