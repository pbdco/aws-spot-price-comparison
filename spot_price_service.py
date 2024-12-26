from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional, Union
import boto3
from botocore.exceptions import ClientError
from redis_cache import RedisCache
import os
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

class SpotPriceService:
    """Service for fetching and caching AWS spot prices."""
    
    def __init__(self, session: Optional[boto3.Session] = None, cache: Optional[RedisCache] = None):
        """Initialize the service with AWS session and Redis cache."""
        self.session = session or self._create_session()
        self.cache = cache
        self.default_region = self.session.region_name or 'us-east-1'
        self.regions = self.get_regions()  # Initialize regions list

    def _create_session(self) -> boto3.Session:
        """Create an AWS session using cached SSO credentials."""
        try:
            # For SSO, just create a default session which will use cached credentials
            return boto3.Session()
        except Exception as e:
            logging.error(f"Failed to use AWS credentials: {e}")
            raise ValueError("No valid AWS credentials found. Make sure you've run 'aws sso login' and the credentials are mounted correctly")

    def get_regions(self) -> List[str]:
        """Get list of available AWS regions, using cache if available."""
        try:
            # Try to get from cache first
            if self.cache:
                cached_regions = self.cache.get_regions()
                if cached_regions:
                    logging.debug("Using cached regions")
                    return cached_regions

            # If not in cache or no cache available, get from AWS
            if not self.session.get_credentials():
                raise ValueError("AWS credentials not configured")
                
            ec2 = self.session.client('ec2', region_name=self.default_region)
            regions = [region['RegionName'] for region in ec2.describe_regions()['Regions']]
            regions = sorted(regions)
            
            if not regions:
                logging.error("No AWS regions found")
                # Fallback to hardcoded list of common regions
                regions = [
                    'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
                    'ca-central-1', 'eu-west-1', 'eu-west-2', 'eu-west-3',
                    'eu-central-1', 'eu-north-1', 'ap-south-1', 'ap-southeast-1',
                    'ap-southeast-2', 'ap-northeast-1', 'ap-northeast-2', 'sa-east-1'
                ]
            
            # Cache the regions if possible
            if self.cache:
                self.cache.set_regions(regions)
                logging.info(f"Updated regions cache with {len(regions)} regions")
            
            return regions
            
        except Exception as e:
            logging.error(f"Error fetching regions: {e}")
            # Return hardcoded list in case of error
            return [
                'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
                'ca-central-1', 'eu-west-1', 'eu-west-2', 'eu-west-3',
                'eu-central-1', 'eu-north-1', 'ap-south-1', 'ap-southeast-1',
                'ap-southeast-2', 'ap-northeast-1', 'ap-northeast-2', 'sa-east-1'
            ]

    def get_spot_price(self, instance_type: str, region: str) -> Dict:
        """Get spot prices for all AZs in a region for a specific instance type."""
        try:
            # Try to get from cache first
            cached_data = self.cache.get_spot_prices(region, instance_type) if self.cache else None
            if cached_data:
                # Force refresh if aws_timestamp is missing (old format data)
                if cached_data.get('aws_timestamp') is None:
                    logging.info(f"Found old format cache data for {instance_type} in {region}, forcing refresh")
                    self.cache.delete_spot_prices(region, instance_type)
                    cached_data = None
                else:
                    logging.debug(f"Cache hit for {instance_type} in {region}")
                    return {
                        'instance_type': instance_type,
                        'region': region,
                        'prices': cached_data.get('prices', {}),
                        'source': 'cache',
                        'aws_timestamp': cached_data['aws_timestamp'],
                        'cached_at': cached_data['cached_at'],
                        'no_prices': cached_data.get('no_prices', False)
                    }

            logging.debug(f"Cache miss for {instance_type} in {region}, fetching from AWS")
            # If not in cache, fetch from AWS
            client = self.session.client('ec2', region_name=region)
            
            logging.debug(f"Requesting spot prices for {instance_type} in {region}")
            try:
                response = client.describe_spot_price_history(
                    InstanceTypes=[instance_type],
                    ProductDescriptions=['Linux/UNIX'],
                    MaxResults=100
                )
            except client.exceptions.ClientError as e:
                if 'InvalidParameterValue' in str(e):
                    # Cache the "no price" result
                    no_price_data = {
                        'prices': {},
                        'aws_timestamp': datetime.now(timezone.utc).isoformat(),
                        'cached_at': datetime.now(timezone.utc).isoformat(),
                        'no_prices': True
                    }
                    if self.cache:
                        self.cache.set_spot_prices(region, instance_type, no_price_data)
                    return {
                        'error': f"No prices found for {instance_type} in {region}",
                        'no_prices': True
                    }
                raise

            prices = {}
            latest_timestamp = None
            
            for price in response['SpotPriceHistory']:
                az = price['AvailabilityZone']
                if az not in prices or price['Timestamp'] > response['SpotPriceHistory'][0]['Timestamp']:
                    prices[az] = float(price['SpotPrice'])
                    latest_timestamp = price['Timestamp']

            if not prices:
                # Cache the "no price" result
                no_price_data = {
                    'prices': {},
                    'aws_timestamp': datetime.now(timezone.utc).isoformat(),
                    'cached_at': datetime.now(timezone.utc).isoformat(),
                    'no_prices': True
                }
                if self.cache:
                    self.cache.set_spot_prices(region, instance_type, no_price_data)
                return {
                    'error': f"No prices found for {instance_type} in {region}",
                    'no_prices': True
                }

            result = {
                'instance_type': instance_type,
                'region': region,
                'prices': prices,
                'source': 'aws',
                'aws_timestamp': latest_timestamp.isoformat() if latest_timestamp else None,
                'cached_at': datetime.now(timezone.utc).isoformat()
            }

            # Cache the result
            if self.cache:
                self.cache.set_spot_prices(region, instance_type, {
                    'prices': prices,
                    'aws_timestamp': result['aws_timestamp'],
                    'cached_at': result['cached_at']
                })

            return result

        except Exception as e:
            logging.error(f"Error getting spot price for {instance_type} in {region}: {e}")
            return {'error': str(e)}

    def get_best_price(self, instance_type: str) -> Dict:
        """Get the best spot price for an instance type across all regions."""
        try:
            best_price = float('inf')
            best_region = None
            best_az = None
            best_timestamp = None
            cache_hits = 0
            cache_misses = 0
            errors = []
            
            # Use ThreadPoolExecutor for parallel price checks
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_region = {
                    executor.submit(self.get_spot_price, instance_type, region): region
                    for region in self.regions
                }
                
                for future in as_completed(future_to_region):
                    region = future_to_region[future]
                    try:
                        result = future.result()
                        if result.get('error'):
                            errors.append({
                                'region': region,
                                'error': result['error']
                            })
                            continue

                        # Track cache hits/misses
                        if result.get('source') == 'cache':
                            cache_hits += 1
                        else:
                            cache_misses += 1
                        
                        # Find the lowest price across all AZs in this region
                        for az, price in result.get('prices', {}).items():
                            price = float(price)
                            if price < best_price:
                                best_price = price
                                best_region = region
                                best_az = az
                                best_timestamp = result.get('aws_timestamp')

                    except Exception as e:
                        errors.append({
                            'region': region,
                            'error': str(e)
                        })

            if best_region is None:
                error_msg = '; '.join([f"{e['region']}: {e['error']}" for e in errors])
                raise ValueError(f"Failed to get prices: {error_msg}")

            return {
                'instance_type': instance_type,
                'region': best_region,
                'az': best_az,
                'price': best_price,
                'aws_timestamp': best_timestamp,  # Original AWS price timestamp
                'timestamp': datetime.now(timezone.utc).isoformat(),  # When we got this result
                'cache_stats': {
                    'hits': cache_hits,
                    'misses': cache_misses,
                    'total': cache_hits + cache_misses
                },
                'errors': errors if errors else None
            }

        except Exception as e:
            logging.error(f"Error getting best price for {instance_type}: {e}")
            raise
