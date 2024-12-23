import os
import boto3
from botocore.exceptions import ClientError
from typing import Optional, Dict
from redis_cache import RedisCache


class SpotPriceService:
    def __init__(self, region: str = None):
        self.region = region or os.getenv('AWS_DEFAULT_REGION', 'ap-south-1')
        self.ec2_client = boto3.client('ec2', region_name=self.region)
        
        # Initialize Redis with environment variables
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', '6379'))
        self.cache = RedisCache(host=redis_host, port=redis_port)
        
        # Default prices as fallback
        self.default_prices = {
            't3a.medium': 0.009,
            't3.nano': 0.0016
        }

    def get_spot_price(self, instance_type: str) -> float:
        """
        Get spot price for instance type with caching.
        Uses cache if available and fresh, otherwise calls AWS API.
        Falls back to default prices if both cache and API fail.
        """
        try:
            # Try cache first
            cached_price = self.cache.get_cached_price(self.region, instance_type)
            if cached_price is not None:
                print(f"Using cached price for {instance_type}: ${cached_price}")
                return cached_price

            # Cache miss or expired, call AWS API
            current_price = self._get_aws_spot_price(instance_type)
            if current_price:
                # Cache the new price
                self.cache.set_price(self.region, instance_type, current_price)
                return current_price

        except Exception as e:
            print(f"Error getting spot price: {str(e)}")

        # Fallback to default price
        return self.default_prices.get(instance_type, 0.009)

    def _get_aws_spot_price(self, instance_type: str) -> Optional[float]:
        """Get current spot price from AWS API."""
        try:
            response = self.ec2_client.describe_spot_price_history(
                InstanceTypes=[instance_type],
                ProductDescriptions=['Linux/UNIX'],
                MaxResults=1
            )
            
            if response['SpotPriceHistory']:
                return float(response['SpotPriceHistory'][0]['SpotPrice'])
            
            return None

        except ClientError as e:
            print(f"AWS API error: {str(e)}")
            return None

    def clear_price_cache(self, instance_type: Optional[str] = None) -> None:
        """Clear price cache for specific instance type or all cache."""
        if instance_type:
            self.cache.clear_cache(self.region, instance_type)
        else:
            self.cache.clear_cache()
