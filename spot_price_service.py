from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional, Union
import boto3
from botocore.exceptions import ClientError
from redis_cache import RedisCache
import os
import json

class SpotPriceService:
    """Service for fetching and caching AWS spot prices."""
    
    def __init__(self, session: Optional[boto3.Session] = None, cache: Optional[RedisCache] = None):
        """Initialize the service with AWS session and Redis cache."""
        self.session = session or self._create_session()
        self.cache = cache
        self.default_region = self.session.region_name or 'us-east-1'

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
        """Get list of available AWS regions."""
        try:
            if not self.session.get_credentials():
                raise ValueError("AWS credentials not configured")
                
            ec2 = self.session.client('ec2', region_name=self.default_region)
            regions = [region['RegionName'] for region in ec2.describe_regions()['Regions']]
            return sorted(regions)
        except Exception as e:
            logging.error(f"Error fetching regions: {e}")
            return []

    def get_spot_price(self, instance_type: str, region: str) -> Dict:
        """Get spot price for a specific instance type and region."""
        try:
            # Try to get from cache first
            cached_data = self.cache.get_spot_prices(region, instance_type) if self.cache else None
            if cached_data and cached_data.get('prices'):
                logging.info(f"Cache hit for {instance_type} in {region}")
                latest_price = sorted(
                    cached_data['prices'],
                    key=lambda x: datetime.fromisoformat(x['timestamp']),
                    reverse=True
                )[0]
                return {
                    'instance_type': instance_type,
                    'region': region,
                    'price': latest_price['price'],
                    'timestamp': latest_price['timestamp'],
                    'availability_zone': latest_price['availability_zone'],
                    'source': 'cache',
                    'cached_at': cached_data.get('cached_at', datetime.now(timezone.utc).isoformat())
                }

            # If not in cache, fetch from AWS
            logging.info(f"Cache miss for {instance_type} in {region}, fetching from AWS")
            price_data = self._get_aws_spot_price(instance_type, region)
            
            if price_data.get('error'):
                return {
                    'instance_type': instance_type,
                    'region': region,
                    'error': price_data['error'],
                    'source': 'aws'
                }

            # Cache the result if valid and cache is available
            if price_data.get('price') and self.cache:
                cache_data = {
                    'prices': [{
                        'price': price_data['price'],
                        'timestamp': price_data['timestamp'],
                        'availability_zone': price_data['availability_zone']
                    }],
                    'cached_at': datetime.now(timezone.utc).isoformat()
                }
                self.cache.set_spot_prices(region, instance_type, cache_data)

            return {
                'instance_type': instance_type,
                'region': region,
                'price': price_data.get('price'),
                'timestamp': price_data.get('timestamp'),
                'availability_zone': price_data.get('availability_zone'),
                'source': 'aws',
                'price_timestamp': price_data.get('price_timestamp'),
                'cached_at': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logging.error(f"Error getting spot price for {instance_type} in {region}: {e}")
            return {
                'instance_type': instance_type,
                'region': region,
                'error': str(e),
                'source': 'error'
            }

    def _get_aws_spot_price(self, instance_type: str, region: str) -> Dict:
        """Get spot price from AWS for a specific instance type and region."""
        try:
            ec2 = self.session.client('ec2', region_name=region)
            
            # Get all AZs in the region
            azs = [az['ZoneName'] for az in ec2.describe_availability_zones()['AvailabilityZones']]
            
            # Get spot prices
            response = ec2.describe_spot_price_history(
                InstanceTypes=[instance_type],
                ProductDescriptions=['Linux/UNIX']
            )
            
            # Create a map of AZ to price
            price_by_az = {}
            for price in response['SpotPriceHistory']:
                az = price['AvailabilityZone']
                if az not in price_by_az or datetime.fromisoformat(price['Timestamp'].isoformat()) > datetime.fromisoformat(price_by_az[az]['timestamp']):
                    price_by_az[az] = {
                        'price': float(price['SpotPrice']),
                        'timestamp': price['Timestamp'].isoformat(),
                        'availability_zone': az
                    }
            
            # Build result including all AZs
            result = {
                'prices': [],
                'cached_at': datetime.now(timezone.utc).isoformat(),
                'instance_available': bool(response['SpotPriceHistory'])
            }
            
            for az in azs:
                if az in price_by_az:
                    result['prices'].append(price_by_az[az])
                else:
                    logging.info(f"No price found for {instance_type} in {az}")
                    result['prices'].append({
                        'price': None,
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'availability_zone': az,
                        'status': 'No price found'
                    })
            
            # Cache the result regardless of whether we found prices
            if self.cache:
                self.cache.set_spot_prices(region, instance_type, result)
            
            if not any(p.get('price') for p in result['prices']):
                return {'error': f'No spot price history found for {instance_type} in {region}'}
            
            # Return the latest valid price
            valid_prices = [p for p in result['prices'] if p.get('price')]
            if not valid_prices:
                return {'error': f'No valid prices found for {instance_type} in {region}'}
                
            latest = sorted(valid_prices, 
                          key=lambda x: datetime.fromisoformat(x['timestamp']),
                          reverse=True)[0]
            
            return {
                'price': latest['price'],
                'timestamp': latest['timestamp'],
                'availability_zone': latest['availability_zone'],
                'price_timestamp': latest['timestamp']
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']
            logging.error(f"AWS error for {region}: {error_code} - {error_msg}")
            
            # Cache error responses too
            if self.cache:
                self.cache.set_spot_prices(region, instance_type, {
                    'prices': [],
                    'cached_at': datetime.now(timezone.utc).isoformat(),
                    'instance_available': False,
                    'error': f"AWS error: {error_code} - {error_msg}"
                })
                
            return {'error': f"AWS error: {error_code} - {error_msg}"}
            
        except Exception as e:
            logging.error(f"Unexpected error for {region}: {e}")
            
            # Cache unexpected errors
            if self.cache:
                self.cache.set_spot_prices(region, instance_type, {
                    'prices': [],
                    'cached_at': datetime.now(timezone.utc).isoformat(),
                    'instance_available': False,
                    'error': f"Unexpected error: {str(e)}"
                })
                
            return {'error': f"Unexpected error: {str(e)}"}

    def get_best_price(self, instance_type: str) -> Dict:
        """Get the best spot price for an instance type across all regions."""
        best_price = float('inf')
        best_region = None
        best_price_data = None
        errors = []

        for region in self.get_regions():
            try:
                price_data = self.get_spot_price(instance_type, region)
                if price_data.get('error'):
                    errors.append(f"{region}: {price_data['error']}")
                    continue
                    
                if price_data.get('price') and price_data['price'] < best_price:
                    best_price = price_data['price']
                    best_region = region
                    best_price_data = price_data
                    
            except Exception as e:
                logging.error(f"Error processing region {region}: {e}")
                errors.append(f"{region}: {str(e)}")

        if not best_region:
            error_msg = "No valid prices found"
            if errors:
                error_msg += f". Errors: {'; '.join(errors[:5])}"
                if len(errors) > 5:
                    error_msg += f" and {len(errors) - 5} more"
            return {'error': error_msg}

        return {
            'instance_type': instance_type,
            'region': best_region,
            'price': best_price,
            'timestamp': best_price_data['timestamp'],
            'availability_zone': best_price_data['availability_zone'],
            'source': best_price_data['source'],
            'price_timestamp': best_price_data.get('price_timestamp'),
            'cached_at': best_price_data.get('cached_at')
        }
