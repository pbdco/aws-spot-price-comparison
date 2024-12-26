import logging
import time
from datetime import datetime, timezone
import os
import signal
import sys
from typing import List, Optional

from redis_cache import RedisCache, TaskStatus, TaskPriority

# Configure logging
root_logger = logging.getLogger()
root_logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# Create console handler with formatting
console_handler = logging.StreamHandler()
console_handler.setFormatter(
    logging.Formatter(
        '%(asctime)s - %(levelname)s - [Scheduler] - %(message)s',
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

class Scheduler:
    """Scheduler process that enqueues periodic update tasks."""
    
    def __init__(self):
        """Initialize the scheduler."""
        self.redis_cache = RedisCache(
            host=os.environ.get('REDIS_HOST', 'localhost'),
            port=int(os.environ.get('REDIS_PORT', 6379)),
            password=os.environ.get('REDIS_PASSWORD')
        )
        self.running = True
        self.update_interval = int(os.environ.get('UPDATE_INTERVAL', 300))  # 5 minutes default
        self.instance_types = self._load_instance_types()
        
        # Set up signal handlers
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)
    
    def handle_signal(self, signum, frame):
        """Handle termination signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    def _load_instance_types(self) -> List[str]:
        """Load list of instance types to monitor from environment."""
        instance_types = os.environ.get('INSTANCE_TYPES', '').split(',')
        if not instance_types or not instance_types[0]:
            # Fallback to default list if not configured
            return [
                't2.micro', 't2.small', 't2.medium',
                't3.micro', 't3.small', 't3.medium',
                'm5.large', 'm5.xlarge',
                'c5.large', 'c5.xlarge'
            ]
        return instance_types
    
    def enqueue_update_task(self):
        """Enqueue a task to update spot prices for all instance types."""
        try:
            task_data = {
                'instance_types': self.instance_types,
                'source': 'scheduler',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            logger.debug(f"Preparing to enqueue update task for instances: {self.instance_types}")
            
            task_id = self.redis_cache.enqueue_task(
                'update_spot_prices',
                task_data,
                TaskPriority.LOW  # Lower priority than API requests
            )
            
            logger.info(f"Enqueued update task {task_id} for {len(self.instance_types)} instance types")
            return task_id
            
        except Exception as e:
            logger.error(f"Error enqueueing update task: {e}")
            return None
    
    def run(self):
        """Main scheduler loop."""
        logger.info("Scheduler starting...")
        last_update = 0
        next_log = 0  # For periodic status logs
        
        while self.running:
            try:
                current_time = time.time()
                
                # Check if it's time for an update
                if current_time - last_update >= self.update_interval:
                    logger.info(f"Starting scheduled update (interval: {self.update_interval}s)")
                    task_id = self.enqueue_update_task()
                    if task_id:
                        last_update = current_time
                        logger.info(f"Successfully scheduled update task {task_id}")
                    else:
                        logger.warning("Failed to schedule update task, will retry soon")
                elif current_time >= next_log:
                    # Log status every minute
                    logger.info(f"Next update in {int(self.update_interval - (current_time - last_update))}s")
                    next_log = current_time + 60  # Next log in 60 seconds
                
                time.sleep(1)  # Sleep for a second before next check
                
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                time.sleep(1)  # Wait a bit before retrying
        
        logger.info("Scheduler shutting down...")

def main():
    """Main entry point for the scheduler process."""
    scheduler = Scheduler()
    scheduler.run()

if __name__ == '__main__':
    main()
