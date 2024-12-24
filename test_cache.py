#!/usr/bin/env python3
import time
from spot_price_service import SpotPriceService

def test_caching():
    """Test spot price caching functionality."""
    service = SpotPriceService()
    instance_type = 't3.nano'

    # First call - should hit AWS API
    print("\n1. First call (AWS API):")
    start = time.time()
    price1 = service.get_spot_price(instance_type)
    duration1 = time.time() - start
    print(f"Price: ${price1}")
    print(f"Duration: {duration1:.2f}s")

    # Second call - should use cache
    print("\n2. Second call (Cache):")
    start = time.time()
    price2 = service.get_spot_price(instance_type)
    duration2 = time.time() - start
    print(f"Price: ${price2}")
    print(f"Duration: {duration2:.2f}s")
    print(f"Cache speedup: {duration1/duration2:.1f}x")

    # Clear cache for instance
    print("\n3. Clearing cache...")
    service.clear_price_cache(instance_type)

    # Third call - should hit AWS API again
    print("\n4. Third call (AWS API after cache clear):")
    start = time.time()
    price3 = service.get_spot_price(instance_type)
    duration3 = time.time() - start
    print(f"Price: ${price3}")
    print(f"Duration: {duration3:.2f}s")

if __name__ == "__main__":
    test_caching()
