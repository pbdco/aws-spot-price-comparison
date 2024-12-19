import boto3
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, timezone
import argparse
from dateutil.parser import isoparse
import threading
import time
import sys
import botocore

def fetch_available_regions(profile_name):
    """Fetch available AWS regions for EC2."""
    try:
        session = boto3.Session(profile_name=profile_name)
        ec2_client = session.client('ec2')
        response = ec2_client.describe_regions()
        return [region['RegionName'] for region in response['Regions']]
    except botocore.exceptions.NoCredentialsError:
        print(f"Error: Unable to locate AWS credentials for profile '{profile_name}'. Please configure your AWS CLI or specify another profile with --profile <name>.")
        stop_loading()
        sys.exit(1)
    except botocore.exceptions.PartialCredentialsError:
        print("Error: Invalid AWS credentials. Please check your credentials.")
        stop_loading()
        sys.exit(1)
    except botocore.exceptions.ProfileNotFound:
        print(f"Error: The specified profile '{profile_name}' does not exist.")
        stop_loading()
        sys.exit(1)

def fetch_spot_price_history(instance_type, region, profile_name):
    try:
        session = boto3.Session(profile_name=profile_name)
        ec2_client = session.client('ec2', region_name=region)

        response = ec2_client.describe_spot_price_history(
            InstanceTypes=[instance_type],
            ProductDescriptions=["Linux/UNIX"],
            StartTime=datetime.now(timezone.utc) - timedelta(days=30),
        )

        return response['SpotPriceHistory']
    except botocore.exceptions.NoCredentialsError:
        print(f"Error: Unable to locate AWS credentials for profile '{profile_name}'. Please configure your AWS CLI or specify another profile with --profile <name>.")
        stop_loading()
        sys.exit(1)
    except botocore.exceptions.PartialCredentialsError:
        print("Error: Invalid AWS credentials. Please check your credentials.")
        stop_loading()
        sys.exit(1)
    except botocore.exceptions.ProfileNotFound:
        print(f"Error: The specified profile '{profile_name}' does not exist.")
        stop_loading()
        sys.exit(1)
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == 'InvalidClientTokenId':
            print("Error: Invalid AWS credentials. Please check your credentials.")
        elif e.response['Error']['Code'] == 'InvalidParameterValue':
            print(f"Error: '{instance_type}' is not a valid EC2 instance type.")
            stop_loading()
            sys.exit(1)  # Exit if the instance type is invalid
        else:
            print(f"An error occurred: {e}")  # Print the original Boto3 error message
        stop_loading()
        sys.exit(1)

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
    global loading
    spinner = ['|', '/', '-', '\\']
    idx = 0
    while loading:
        sys.stdout.write(f'\rLoading data... {spinner[idx]}')
        sys.stdout.flush()
        idx = (idx + 1) % len(spinner)
        time.sleep(0.2)

def stop_loading():
    global loading
    loading = False

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

    try:
        # Fetch available regions from AWS
        available_regions = fetch_available_regions(profile_name)

        # Validate provided regions
        for region in args.regions:
            if region not in available_regions:
                print(f"Error: '{region}' is not a valid AWS region.\n")
                print("Valid regions are:")
                for valid_region in available_regions:
                    print(f" - {valid_region}")
                stop_loading()
                sys.exit(1)

        region_data = {}

        for region in args.regions:
            spot_price_data = fetch_spot_price_history(instance_type, region, profile_name)
            if not spot_price_data:  # Check if no data was returned
                print(f"Error: No spot price data available for instance type '{instance_type}' in region '{region}'.")
                stop_loading()
                sys.exit(1)

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

    except KeyboardInterrupt:
        print("\n\nBye!")  # Graceful exit message
        stop_loading()
        sys.exit(0)
