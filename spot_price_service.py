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
        self.total_workers = int(os.environ.get('GUNICORN_WORKERS', '1'))

    def _create_session(self) -> boto3.Session:
        """Create an AWS session using mounted credentials."""
        try:
            # Just use the mounted AWS config/credentials
            profile = os.environ.get('AWS_PROFILE')
            if profile:
                logging.info(f"Using mounted AWS profile: {profile}")
                return boto3.Session(profile_name=profile)
            else:
                logging.info("Using default AWS profile")
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
        best_price = float('inf')
        best_region = None
        best_az = None
        best_price_data = None
        errors = []
        processed_regions = 0
        all_regions = set(self.regions)
        processed_regions_set = set()

        # Generate a unique request ID
        request_id = f"best_price_request_{instance_type}_{time.time()}"
        self.cache.init_best_price_request(request_id, len(self.regions))
        
        # Process regions in parallel using ThreadPoolExecutor
        max_workers = min(20, len(self.regions))  # Use up to 20 threads
        
        def process_region(region):
            try:
                price_data = self.get_spot_price(instance_type, region)
                if price_data.get('error'):
                    return {'error': f"{region}: {price_data['error']}"}
                
                prices = price_data.get('prices', {})
                if not prices:
                    return {'error': f"No prices found for {instance_type} in {region}"}
                
                region_best = float('inf')
                region_az = None
                region_timestamp = None
                region_cached_at = None
                
                for az, price in prices.items():
                    try:
                        price_float = float(price)
                        if price_float < region_best:
                            region_best = price_float
                            region_az = az
                            region_timestamp = price_data.get('aws_timestamp')
                            region_cached_at = price_data.get('cached_at')
                    except (ValueError, TypeError) as e:
                        logging.error(f"Invalid price value for {instance_type} in {region}/{az}: {e}")
                        continue
                
                if region_best < float('inf'):
                    result = {
                        'instance_type': instance_type,
                        'region': region,
                        'price': region_best,
                        'availability_zone': region_az,
                        'source': price_data['source'],
                        'aws_timestamp': region_timestamp,
                        'cached_at': region_cached_at
                    }
                    # Store result in Redis for other workers to see
                    self.cache.update_best_price_partial(request_id, result)
                    return result
                    
                return {'error': f"No valid prices for {instance_type} in {region}"}
            except Exception as e:
                return {'error': f"{region}: {str(e)}"}

        # Process all regions in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_region = {executor.submit(process_region, region): region for region in self.regions}
            
            for future in as_completed(future_to_region):
                region = future_to_region[future]
                try:
                    result = future.result()
                    processed_regions_set.add(region)
                    
                    if 'error' in result:
                        errors.append(result['error'])
                        continue
                    
                    if result['price'] < best_price:
                        best_price = result['price']
                        best_region = result['region']
                        best_az = result['availability_zone']
                        best_price_data = result
                        
                except Exception as e:
                    errors.append(f"{region}: {str(e)}")

        # Get results from other workers via Redis
        all_results = self.cache.get_best_price_results(request_id) or []
        for result in all_results:
            try:
                if isinstance(result, dict) and 'price' in result and 'region' in result:
                    processed_regions_set.add(result['region'])
                    price = float(result['price'])
                    if price < best_price:
                        best_price = price
                        best_region = result['region']
                        best_az = result['availability_zone']
                        best_price_data = result
            except (ValueError, TypeError, KeyError) as e:
                logging.error(f"Invalid result data: {e}")
                continue

        # Check if we've processed all regions
        unprocessed_regions = all_regions - processed_regions_set
        if unprocessed_regions:
            logging.warning(f"Some regions were not processed: {unprocessed_regions}")
            errors.append(f"Regions not processed: {', '.join(sorted(unprocessed_regions)[:5])}")
            if len(unprocessed_regions) > 5:
                errors.append(f"and {len(unprocessed_regions) - 5} more")

        # Only return error if we have no valid prices
        if not best_price_data:
            error_msg = "; ".join(errors[:5])
            if len(errors) > 5:
                error_msg += f" and {len(errors) - 5} more errors"
            return {'error': error_msg}

        # Return the best price we found
        return best_price_data
