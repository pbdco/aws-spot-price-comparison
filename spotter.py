import boto3
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, timezone
import argparse
from dateutil.parser import isoparse
import threading
import time
import sys

ALL_REGIONS = [
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "ap-south-1", "ap-northeast-3", "ap-northeast-2", "ap-southeast-1",
    "ap-southeast-2", "ap-northeast-1", "ca-central-1",
    "eu-central-1", "eu-west-1", "eu-west-2", "eu-west-3", "eu-north-1",
    "sa-east-1"
]

def fetch_spot_price_history(instance_type, region, profile_name):
    session = boto3.Session(profile_name=profile_name)
    ec2_client = session.client('ec2', region_name=region)

    response = ec2_client.describe_spot_price_history(
        InstanceTypes=[instance_type],
        ProductDescriptions=["Linux/UNIX"],
        StartTime=datetime.now(timezone.utc) - timedelta(days=30),
    )

    return response['SpotPriceHistory']

def process_spot_price_data(data, days):
    prices = []
    timestamps = []
    target_date = datetime.now(timezone.utc) - timedelta(days=days)

    for entry in data:
        price = float(entry['SpotPrice'])
        timestamp_str = entry['Timestamp']

        if isinstance(timestamp_str, str):
            timestamp = isoparse(timestamp_str)
        elif isinstance(timestamp_str, datetime):
            timestamp = timestamp_str
        else:
            continue

        if timestamp >= target_date:
            prices.append(price)
            timestamps.append(timestamp)

    return timestamps, prices

def plot_spot_prices(region_data, instance_type):
    plt.figure(figsize=(12, 6))
    colors = ['blue', 'orange', 'green', 'red', 'purple', 'cyan', 'magenta', 'brown', 'pink', 'gray', 'olive', 'teal', 'navy', 'gold']

    for idx, (region, (timestamps, prices)) in enumerate(region_data.items()):
        plt.plot(timestamps, prices, marker='o', linestyle='-', color=colors[idx % len(colors)], label=region)

    plt.title(f'AWS EC2 Spot Prices Comparison for {instance_type}')
    plt.xlabel('Timestamp')
    plt.ylabel('Spot Price ($)')
    plt.xticks(rotation=45)
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.show()

def loading_animation():
    spinner = ['|', '/', '-', '\\']
    idx = 0
    while loading:
        sys.stdout.write(f'\rLoading data... {spinner[idx]}')
        sys.stdout.flush()
        idx = (idx + 1) % len(spinner)
        time.sleep(0.2)

if __name__ == "__main__":
    loading = True
    loading_thread = threading.Thread(target=loading_animation)
    loading_thread.start()

    parser = argparse.ArgumentParser(description='Fetch and plot AWS EC2 spot prices.')
    parser.add_argument('days', type=int, nargs='?', default=30, help='Number of days to show in the graph (default: 30)')
    parser.add_argument('regions', type=str, nargs='*', default=['ap-south-1'], help='AWS region(s) (default: ap-south-1)')
    parser.add_argument('--instance_type', type=str, default='t3.medium', help='EC2 instance type (default: t3.medium)')
    parser.add_argument('--profile', type=str, default='default', help='AWS profile name (default: default)')
    args = parser.parse_args()

    instance_type = args.instance_type
    profile_name = args.profile

    region_data = {}

    if "all" in args.regions:
        args.regions = ALL_REGIONS
    elif not args.regions:
        args.regions = ['ap-south-1']

    for region in args.regions:
        spot_price_data = fetch_spot_price_history(instance_type, region, profile_name)
        timestamps, prices = process_spot_price_data(spot_price_data, args.days)
        region_data[region] = (timestamps, prices)

    loading = False
    loading_thread.join()

    print(f"\nDate and Spot Prices for {instance_type}:")
    best_price = float('inf')
    best_price_region = None
    for region, (timestamps, prices) in region_data.items():
        print(f"\nRegion: {region}")
        for timestamp, price in zip(timestamps, prices):
            print(f"{timestamp.strftime('%Y-%m-%d %H:%M:%S')} - ${price:.5f}")

        if prices:
            average_price = sum(prices) / len(prices)
            latest_price = prices[-1]
            print(f"Average Price: ${average_price:.5f}")
            print(f"Latest Price: ${latest_price:.5f}")

            if latest_price < best_price:
                best_price = latest_price
                best_price_region = region
        else:
            print("No prices available for this region.")

    if best_price_region:
        print(f"\nBest current Price for {instance_type}: ${best_price:.5f} in region: {best_price_region}")

    plot_spot_prices(region_data, instance_type)
