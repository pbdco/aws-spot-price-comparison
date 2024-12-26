import logging
import time
from datetime import datetime, timezone
import os
import signal
import sys
from typing import Optional

from redis_cache import RedisCache, TaskStatus, TaskPriority
from spot_price_service import SpotPriceService

# Configure logging
root_logger = logging.getLogger()
root_logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# Create console handler with formatting
console_handler = logging.StreamHandler()
console_handler.setFormatter(
    logging.Formatter(
        '%(asctime)s - %(levelname)s - [Worker] - %(message)s',
        '%Y-%m-%d %H:%M:%S'
    )
)

# Remove any existing handlers and add our configured one
root_logger.handlers.clear()
root_logger.addHandler(console_handler)

# Configure boto3 and botocore loggers to use our handler
for logger_name in ['boto3', 'botocore', 'urllib3']:
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    logger.addHandler(console_handler)
    logger.setLevel(logging.WARNING)  # Set to WARNING to reduce noise

logger = logging.getLogger(__name__)

class Worker:
    """Worker process that handles tasks from the queue."""
    
    def __init__(self):
        """Initialize the worker."""
        self.redis_cache = RedisCache(
            host=os.environ.get('REDIS_HOST', 'localhost'),
            port=int(os.environ.get('REDIS_PORT', 6379)),
            password=os.environ.get('REDIS_PASSWORD')
        )
        self.running = True
        self.spot_service = SpotPriceService(cache=self.redis_cache)
        
        # Set up signal handlers
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)
    
    def handle_signal(self, signum, frame):
        """Handle termination signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    def process_task(self, task: dict) -> bool:
        """Process a single task."""
        task_id = task['task_id']
        task_type = task['type']
        task_data = task.get('data', {})
        source = task_data.get('source', 'unknown')
        
        logger.info(f"Processing task {task_id} ({source}) of type {task_type}")
        
        try:
            if task_type == 'get_best_price':
                instance_type = task_data['instance_type']
                logger.info(f"[Task {task_id}] Fetching best price for {instance_type}")
                
                result = self.spot_service.get_best_price(instance_type)
                logger.debug(f"[Task {task_id}] Got result for {instance_type}: {result}")
                
                self.redis_cache.set_task_result(task_id, result)
                logger.info(f"[Task {task_id}] Completed price fetch for {instance_type}")
                return True
                
            elif task_type == 'update_spot_prices':
                instance_types = task_data.get('instance_types', [])
                logger.info(f"[Task {task_id}] Starting batch update for {len(instance_types)} instance types")
                
                for idx, instance_type in enumerate(instance_types, 1):
                    try:
                        logger.info(f"[Task {task_id}] ({idx}/{len(instance_types)}) Updating {instance_type}")
                        result = self.spot_service.get_best_price(instance_type.strip())
                        logger.debug(f"[Task {task_id}] Got price for {instance_type}: {result}")
                    except Exception as e:
                        logger.error(f"[Task {task_id}] Error updating {instance_type}: {e}")
                
                logger.info(f"[Task {task_id}] Completed batch update of {len(instance_types)} instances")
                return True
                
            else:
                logger.warning(f"[Task {task_id}] Unknown task type: {task_type}")
                self.redis_cache.set_task_error(task_id, f"Unknown task type: {task_type}")
                return False
                
        except Exception as e:
            logger.error(f"[Task {task_id}] Error processing task: {e}")
            self.redis_cache.set_task_error(task_id, str(e))
            return False
    
    def run(self):
        """Main worker loop."""
        logger.info("Worker starting...")
        
        while self.running:
            try:
                # Check for stale tasks every minute
                if int(time.time()) % 60 == 0:
                    requeued = self.redis_cache.requeue_stale_tasks()
                    if requeued:
                        logger.info(f"Requeued {requeued} stale tasks")
                
                # Get next task with priority
                task = self.redis_cache.get_next_task()
                
                if task:
                    self.process_task(task)
                else:
                    time.sleep(0.1)  # Short sleep when no tasks
                    
            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
                time.sleep(1)
        
        logger.info("Worker shutting down...")

def main():
    """Main entry point for the worker process."""
    worker = Worker()
    worker.run()

if __name__ == '__main__':
    main()
