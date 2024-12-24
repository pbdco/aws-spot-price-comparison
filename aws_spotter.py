#!/usr/bin/env python3

from typing import List, Dict, Tuple, Optional
import boto3
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, timezone
import argparse
from dateutil.parser import isoparse, parser
from datetime import datetime
import threading
import time
import sys
import logging
import botocore
from dataclasses import dataclass
import textwrap
import numpy as np
import json
import os
import redis

# Constants
DEFAULT_DAYS = 30
DEFAULT_REGION = "ap-south-1"
DEFAULT_INSTANCE_TYPE = "t3.medium"
DEFAULT_PROFILE = "default"
FETCH_ALL_REGIONS = True

# ANSI Colors
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"
CYAN = "\033[96m"

class RedisCache:
    def __init__(self, host: str, port: int, password: str = None):
        self.redis_client = redis.Redis(host=host, port=port, password=password)

    def fetch_lock(self, name: str):
        return self.redis_client.lock(name, timeout=30, blocking_timeout=0)

    def get_lock_time_remaining(self, name: str):
        return self.redis_client.pttl(name)

    def set_prices(self, region: str, instance_type: str, prices: List[float]):
        self.redis_client.hset(f"prices:{region}:{instance_type}", mapping={"prices": json.dumps(prices)})

class SpotPriceService:
    def __init__(self, session: boto3.Session, cache: RedisCache):
        self.session = session
        self.cache = cache

    def get_regions(self) -> List[str]:
        try:
            ec2_client = self.session.client('ec2', region_name=DEFAULT_REGION)
            response = ec2_client.describe_regions()
            return [region['RegionName'] for region in response['Regions']]
        except Exception as e:
            raise Exception(f"Error fetching regions: {str(e)}")

    def get_spot_price_by_region(self, instance_type: str, region: str) -> List[float]:
        try:
            ec2_client = self.session.client('ec2', region_name=region)
            response = ec2_client.describe_spot_price_history(
                InstanceTypes=[instance_type],
                ProductDescriptions=["Linux/UNIX"],
                StartTime=datetime.now(timezone.utc) - timedelta(days=DEFAULT_DAYS),
            )
            return [float(item['SpotPrice']) for item in response['SpotPriceHistory']]
        except botocore.exceptions.ClientError as e:
            raise Exception(f"Error fetching prices for {instance_type} in {region}: {str(e)}")

def parse_args():
    parser = argparse.ArgumentParser(description='AWS Spot Price Analyzer')
    parser.add_argument('--days', type=int, default=DEFAULT_DAYS,
                      help=f'Number of days of history to analyze (default: {DEFAULT_DAYS})')
    parser.add_argument('--instance-type', type=str, default=DEFAULT_INSTANCE_TYPE,
                      help=f'EC2 instance type to analyze (default: {DEFAULT_INSTANCE_TYPE})')
    parser.add_argument('--regions', type=str, default=DEFAULT_REGION,
                      help=f'Comma-separated list of regions or "all" (default: {DEFAULT_REGION})')
    parser.add_argument('--profile', type=str, default=DEFAULT_PROFILE,
                      help=f'AWS profile to use (default: {DEFAULT_PROFILE})')
    parser.add_argument('--detailed', action='store_true',
                      help='Show detailed information for each region')
    parser.add_argument('--json', action='store_true',
                      help='Output in JSON format')
    parser.add_argument('--no-graph', action='store_true',
                      help='Skip graph generation')
    parser.add_argument('--interval', type=int, default=0,
                      help='Run continuously with specified interval in seconds')
    parser.add_argument('--once', action='store_true',
                      help='Run once and exit (even in Docker)')
    
    return parser.parse_args()

def main():
    """Main function."""
    args = parse_args()
    
    # Initialize services
    redis_cache = RedisCache(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', '6379')),
        password=os.getenv('REDIS_PASSWORD')
    )
    
    session = boto3.Session(region_name=os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'))
    spot_service = SpotPriceService(session=session, cache=redis_cache)
    
    # Get instance types from environment or args
    instance_types = os.getenv('INSTANCE_TYPES', '').split(',') if os.getenv('INSTANCE_TYPES') else [args.instance_type]
    if not instance_types:
        instance_types = ['t2.micro', 't2.small', 't2.medium']
    
    # Get all regions
    try:
        regions = spot_service.get_regions()
        logging.info(f"Successfully fetched {len(regions)} regions")
    except Exception as e:
        logging.error(f"Error fetching regions: {e}")
        regions = [os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')]
    
    logging.info(f"Monitoring instance types: {instance_types}")
    logging.info(f"Monitoring regions: {regions}")
    
    while True:
        try:
            # Try to acquire fetch lock
            with redis_cache.fetch_lock("fetch_prices") as got_lock:
                if not got_lock:
                    # Another process is fetching, wait for next interval
                    remaining = redis_cache.get_lock_time_remaining("fetch_prices")
                    logging.info(f"Fetch already in progress. Waiting for {remaining}s...")
                    time.sleep(min(30, remaining or 30))  # Wait at most 30 seconds
                    continue
                
                # We got the lock, do the fetch
                for instance_type in instance_types:
                    for region in regions:
                        try:
                            logging.info(f"Fetching prices for {instance_type} in {region}")
                            prices = spot_service.get_spot_price_by_region(instance_type, region)
                            if prices:
                                redis_cache.set_prices(region, instance_type, prices)
                                logging.info(f"Cached prices for {instance_type} in {region}: {prices}")
                        except Exception as e:
                            logging.error(f"Error fetching prices for {instance_type} in {region}: {e}")
                            continue
            
            # Sleep for the specified interval
            interval = int(os.getenv('UPDATE_INTERVAL', args.interval))
            logging.info(f"Sleeping for {interval} seconds...")
            time.sleep(interval)
            
        except KeyboardInterrupt:
            logging.info("Stopping price monitoring...")
            break
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            time.sleep(10)  # Sleep briefly before retrying

if __name__ == "__main__":
    logging.basicConfig(
        format='%(asctime)s - %(levelname)s - %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    main()
