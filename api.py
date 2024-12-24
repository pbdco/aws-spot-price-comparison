from flask import Flask, jsonify, request, make_response
import logging
import os
from datetime import datetime, timezone
from functools import wraps
import threading
import time
from typing import Dict, Optional
import multiprocessing
import socket

from spot_price_service import SpotPriceService
from redis_cache import RedisCache

# Configure logging
logging.basicConfig(
    level=os.environ.get('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Initialize Flask app
app = Flask(__name__)

# Initialize Redis cache
redis_host = os.environ.get('REDIS_HOST', 'redis')
redis_port = int(os.environ.get('REDIS_PORT', 6379))
redis_password = os.environ.get('REDIS_PASSWORD')

redis_cache = RedisCache(
    host=redis_host,
    port=redis_port,
    password=redis_password
)

# Initialize spot price service
spot_service = SpotPriceService(cache=redis_cache)

# Get configuration
UPDATE_INTERVAL = int(os.environ.get('UPDATE_INTERVAL', 300))  # 5 minutes default
INSTANCE_TYPES = os.environ.get('INSTANCE_TYPES', '').split(',')

def is_primary_worker():
    """Check if this is the primary worker process using Redis lock."""
    try:
        # First verify Redis connection
        if not redis_cache.client.ping():
            logging.error("Redis connection failed")
            return False

        lock_key = "spot_price_leader_lock"
        my_id = str(os.getpid())
        
        # Try to acquire the lock with NX and expiry
        acquired = redis_cache.set(lock_key, my_id, ex=30, nx=True)
        
        if acquired:
            logging.info(f"Worker {my_id} acquired leadership")
            return True
            
        # If we didn't acquire it, check if we're already the leader
        current_leader = redis_cache.get(lock_key)
        if current_leader == my_id:
            # Refresh our lock
            redis_cache.set(lock_key, my_id, ex=30)
            return True
            
        return False
        
    except Exception as e:
        logging.error(f"Error in leader election: {e}")
        return False

def update_prices():
    """Background task to update spot prices for all configured instance types."""
    my_id = os.getpid()
    logging.info(f"Price update process started for worker {my_id}")
    
    while True:
        try:
            if not is_primary_worker():
                logging.debug(f"Worker {my_id} is not the leader, waiting...")
                time.sleep(10)
                continue
                
            logging.info(f"Worker {my_id} starting periodic price update")
            regions = spot_service.get_regions()
            
            for instance_type in INSTANCE_TYPES:
                if not instance_type.strip():
                    continue
                    
                logging.info(f"Updating prices for {instance_type}")
                for region in regions:
                    try:
                        spot_service.get_spot_price(instance_type.strip(), region)
                    except Exception as e:
                        logging.error(f"Error updating price for {instance_type} in {region}: {e}")
                        
            logging.info(f"Worker {my_id} finished periodic price update")
            time.sleep(UPDATE_INTERVAL)
            
        except Exception as e:
            logging.error(f"Error in price update process: {e}")
            time.sleep(10)

# Start the background update process only on the primary worker
if INSTANCE_TYPES and INSTANCE_TYPES[0] and is_primary_worker():
    logging.info("Starting price update process")
    update_process = multiprocessing.Process(target=update_prices, daemon=True)
    update_process.start()
else:
    logging.info("Not the primary worker, skipping price update process")

# Security and rate limiting configuration
RATE_LIMIT = int(os.environ.get('RATE_LIMIT', '60'))  # requests per minute
RATE_LIMIT_WINDOW = 60  # seconds
CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS', '*')

def add_security_headers(response):
    """Add security headers to response."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Access-Control-Allow-Origin'] = CORS_ALLOWED_ORIGINS
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

def format_error_response(message: str, status_code: int = 500) -> Dict:
    """Format error response with timestamp and status code."""
    response = {
        'error': message,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'status_code': status_code
    }
    return response

def rate_limit(f):
    """Rate limiting decorator using Redis."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'OPTIONS':
            response = make_response()
            return add_security_headers(response)
            
        # Get client IP
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        current = int(time.time())
        key = f'rate_limit:{client_ip}:{current // RATE_LIMIT_WINDOW}'
        
        try:
            # Increment counter
            current_requests = redis_cache._retry_operation(
                redis_cache.client.incr,
                key
            )
            
            # Set expiry on first request
            if current_requests == 1:
                redis_cache._retry_operation(
                    redis_cache.client.expire,
                    key,
                    RATE_LIMIT_WINDOW
                )
            
            # Check if over limit
            if current_requests > RATE_LIMIT:
                logging.warning(f"Rate limit exceeded for {client_ip}")
                return format_error_response(
                    "Rate limit exceeded. Please try again later.",
                    429
                )
            
            # Add rate limit headers
            response = f(*args, **kwargs)
            if isinstance(response, tuple):
                response, status_code = response
            else:
                status_code = 200
                
            remaining = max(0, RATE_LIMIT - current_requests)
            reset_time = (current // RATE_LIMIT_WINDOW + 1) * RATE_LIMIT_WINDOW
            
            if isinstance(response, (str, dict)):
                response = make_response(jsonify(response) if isinstance(response, dict) else response)
            
            response.headers.update({
                'X-RateLimit-Limit': str(RATE_LIMIT),
                'X-RateLimit-Remaining': str(remaining),
                'X-RateLimit-Reset': str(reset_time)
            })
            
            response = add_security_headers(response)
            response.status_code = status_code
            return response
            
        except Exception as e:
            logging.error(f"Error in rate limiter: {e}")
            # Continue if rate limiting fails
            response = f(*args, **kwargs)
            if isinstance(response, (str, dict)):
                response = make_response(jsonify(response) if isinstance(response, dict) else response)
            return add_security_headers(response)
            
    return decorated_function

@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors."""
    return format_error_response("Resource not found", 404)

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logging.error(f"Internal server error: {error}")
    return format_error_response("Internal server error", 500)

@app.route('/', methods=['GET', 'OPTIONS'])
@rate_limit
def list_endpoints():
    """List all available API endpoints."""
    return jsonify({
        'endpoints': {
            '/': {
                'methods': ['GET'],
                'description': 'List all available API endpoints'
            },
            '/spot-prices/<region>/<instance_type>': {
                'methods': ['GET'],
                'description': 'Get spot prices for a specific instance type in a region',
                'parameters': {
                    'region': 'AWS region (e.g., us-east-1)',
                    'instance_type': 'EC2 instance type (e.g., t2.micro)',
                    'history': 'Optional query parameter (true/false) to include price history'
                },
                'response': {
                    'instance_type': 'The requested instance type',
                    'region': 'The requested region',
                    'latest_price': 'The latest spot price',
                    'cached_at': 'The timestamp when the data was cached',
                    'price_history': 'Optional price history',
                    'source': 'Whether data came from cache or aws'
                }
            },
            '/spot-prices/best/<instance_type>': {
                'methods': ['GET'],
                'description': 'Get the best (lowest) spot price across all regions for an instance type',
                'parameters': {
                    'instance_type': 'EC2 instance type (e.g., t2.micro)'
                },
                'response': {
                    'instance_type': 'The requested instance type',
                    'best_price': 'The lowest spot price found',
                    'region': 'The region with the lowest price',
                    'availability_zone': 'The availability zone with the lowest price',
                    'timestamp': 'The timestamp of the lowest price',
                    'source': 'Whether data came from cache or aws'
                }
            },
            '/health': {
                'methods': ['GET'],
                'description': 'Health check endpoint',
                'response': {
                    'status': 'Health status of the service',
                    'timestamp': 'Current timestamp',
                    'services': {
                        'redis': 'Redis connection status',
                        'aws': 'AWS connection status'
                    }
                }
            }
        }
    })

@app.route('/spot-prices/<region>/<instance_type>', methods=['GET', 'OPTIONS'])
@rate_limit
def get_spot_prices(region, instance_type):
    """Get spot prices for a specific instance type in a region."""
    try:
        logging.info(f"Getting spot price for {instance_type} in {region}")
        price_data = spot_service.get_spot_price(instance_type, region)
        
        if price_data.get('error'):
            return format_error_response(price_data['error'], 404)
            
        response = make_response(jsonify(price_data))
        return add_security_headers(response)
        
    except Exception as e:
        logging.error(f"Error in get_spot_prices: {e}")
        return format_error_response(str(e))

@app.route('/spot-prices/best/<instance_type>', methods=['GET', 'OPTIONS'])
@rate_limit
def get_best_price(instance_type):
    """Get the best spot price across all regions for an instance type."""
    try:
        logging.info(f"Finding best price for {instance_type}")
        price_data = spot_service.get_best_price(instance_type)
        
        if price_data.get('error'):
            return format_error_response(price_data['error'], 404)
            
        response = make_response(jsonify(price_data))
        return add_security_headers(response)
        
    except Exception as e:
        logging.error(f"Error in get_best_price: {e}")
        return format_error_response(str(e))

@app.route('/health', methods=['GET', 'OPTIONS'])
@rate_limit
def health_check():
    """Health check endpoint."""
    health_status = {
        'status': 'healthy',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'services': {
            'redis': 'healthy',
            'aws': 'healthy'
        }
    }

    # Check Redis health
    try:
        redis_cache._retry_operation(redis_cache.client.ping)
    except Exception as e:
        health_status['services']['redis'] = f'unhealthy: {str(e)}'
        health_status['status'] = 'degraded'
        logging.error(f"Redis health check failed: {e}")

    # Check AWS health - just verify credentials without making API call
    try:
        if not spot_service.session.get_credentials():
            health_status['services']['aws'] = 'unhealthy: no credentials found'
            health_status['status'] = 'degraded'
            logging.warning("AWS credentials not found")
    except Exception as e:
        health_status['services']['aws'] = f'unhealthy: {str(e)}'
        health_status['status'] = 'degraded'
        logging.error(f"AWS health check failed: {e}")

    status_code = 200 if health_status['status'] == 'healthy' else 503
    response = make_response(jsonify(health_status), status_code)
    return add_security_headers(response)

if __name__ == '__main__':
    port = int(os.environ.get('API_PORT', 5001))
    host = os.environ.get('API_HOST', '0.0.0.0')
    logging.info(f"Starting server on {host}:{port}")
    app.run(host=host, port=port)
