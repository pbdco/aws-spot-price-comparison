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

# Constants
DEFAULT_DAYS = 30
DEFAULT_REGION = "ap-south-1"
DEFAULT_INSTANCE_TYPE = "t3.medium"
DEFAULT_PROFILE = "default"

# ANSI Colors
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"
CYAN = "\033[96m"

def parse_regions(regions_str: str, profile: str = DEFAULT_PROFILE) -> List[str]:
    """Parse comma-separated regions string into a list."""
    if not regions_str:
        return [DEFAULT_REGION]

    if regions_str.lower() == 'all':
        try:
            # Use environment variables if available, otherwise use profile
            if 'AWS_ACCESS_KEY_ID' in os.environ and 'AWS_SECRET_ACCESS_KEY' in os.environ:
                session = boto3.Session(
                    aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
                    aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
                    aws_session_token=os.environ.get('AWS_SESSION_TOKEN'),
                    region_name=DEFAULT_REGION
                )
            else:
                session = boto3.Session(profile_name=profile)
            
            ec2_client = session.client('ec2', region_name=DEFAULT_REGION)
            response = ec2_client.describe_regions()
            return [region['RegionName'] for region in response['Regions']]
        except Exception as e:
            raise AWSError(
                "Could not fetch regions. Make sure AWS credentials are configured.",
                help_text=(
                    "\nTo fix AWS credentials issues:\n"
                    "1. Configure AWS CLI: aws configure\n"
                    "2. Or specify a profile: --profile your-profile-name\n"
                    "3. Make sure your credentials are valid and not expired\n"
                    "4. For SSO profiles, run: aws sso login --profile your-profile-name"
                )
            )

    return [r.strip() for r in regions_str.split(',') if r.strip()]

@dataclass
class SpotPriceConfig:
    """Configuration for spot price analysis."""
    days: int
    instance_type: str
    regions: List[str]
    profile: str
    detailed: bool
    json_mode: bool
    no_graph: bool
    availability_zone: Optional[str] = None

    def __post_init__(self):
        if self.regions is None:
            self.regions = [DEFAULT_REGION]
        if self.days <= 0:
            raise ValueError("Days must be a positive integer")

class AWSError(Exception):
    """Custom exception for AWS-related errors."""
    def __init__(self, message: str, help_text: str = None):
        self.message = message
        self.help_text = help_text
        super().__init__(self.message)

class SpotPriceAnalyzer:
    def __init__(self, config: SpotPriceConfig):
        self.config = config
        self.loading = False
        self.loading_thread: Optional[threading.Thread] = None
        try:
            # First try environment variables
            if 'AWS_ACCESS_KEY_ID' in os.environ and 'AWS_SECRET_ACCESS_KEY' in os.environ:
                self.session = boto3.Session(
                    aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
                    aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
                    aws_session_token=os.environ.get('AWS_SESSION_TOKEN'),
                    region_name=DEFAULT_REGION
                )
            else:
                self.session = boto3.Session(profile_name=config.profile)
        except botocore.exceptions.ProfileNotFound:
            raise AWSError(
                f"AWS profile '{config.profile}' not found",
                help_text=(
                    "\nTo fix this:\n"
                    "1. Check your AWS credentials file (~/.aws/credentials)\n"
                    "2. Ensure the profile exists and is correctly configured\n"
                    "3. Available profiles can be found in ~/.aws/credentials\n"
                    "4. Use --profile <n> to specify a different profile"
                )
            )
        except Exception as e:
            raise AWSError(
                f"Failed to initialize AWS session: {str(e)}",
                help_text=(
                    "\nTo fix this:\n"
                    "1. Make sure your AWS credentials are valid\n"
                    "2. Check if your credentials have expired\n"
                    "3. Ensure you have the necessary permissions"
                )
            )

    def fetch_available_regions(self) -> List[str]:
        """Fetch available AWS regions for EC2."""
        try:
            ec2_client = self.session.client('ec2', region_name=DEFAULT_REGION)  
            response = ec2_client.describe_regions()
            return [region['RegionName'] for region in response['Regions']]
        except botocore.exceptions.UnauthorizedSSOTokenError:
            raise AWSError(
                "AWS SSO session has expired",
                help_text=(
                    "\nTo fix this:\n"
                    f"1. Run: aws sso login --profile {self.config.profile}\n"
                    "2. Wait for the login process to complete\n"
                    "3. Try running this script again"
                )
            )
        except (botocore.exceptions.NoCredentialsError,
                botocore.exceptions.PartialCredentialsError) as e:
            raise AWSError(
                f"AWS credentials error for profile '{self.config.profile}'",
                help_text=(
                    "\nTo fix this:\n"
                    "1. Configure your AWS CLI: aws configure --profile {self.config.profile}\n"
                    "2. Ensure your credentials are valid\n"
                    "3. Specify another profile with --profile <name>"
                )
            )
        except botocore.exceptions.ClientError as e:
            raise AWSError(f"AWS API error: {str(e)}")

    def fetch_spot_price_history(self, region: str) -> List[Dict]:
        """Fetch spot price history for a specific region."""
        try:
            ec2_client = self.session.client('ec2', region_name=region)
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=self.config.days)

            filters = [{'Name': 'instance-type', 'Values': [self.config.instance_type]}]
            if self.config.availability_zone:
                filters.append({'Name': 'availability-zone', 'Values': [self.config.availability_zone]})

            paginator = ec2_client.get_paginator('describe_spot_price_history')
            spot_prices = []

            for page in paginator.paginate(
                StartTime=start_time,
                EndTime=end_time,
                InstanceTypes=[self.config.instance_type],
                ProductDescriptions=['Linux/UNIX'],
                Filters=filters
            ):
                spot_prices.extend(page['SpotPriceHistory'])
            return spot_prices
        except botocore.exceptions.ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'InvalidParameterValue':
                raise AWSError(
                    f"Invalid instance type: '{self.config.instance_type}'",
                    help_text=(
                        "\nValid instance type format examples:\n"
                        " - t3.micro\n"
                        " - c5.xlarge\n"
                        " - m5.2xlarge\n"
                        "\nFind valid instance types at:\n"
                        "https://aws.amazon.com/ec2/instance-types/"
                    )
                )
            raise AWSError(f"AWS API error: {str(e)}")

    def process_spot_price_data(self, data: List[Dict]) -> Tuple[List[datetime], List[float], List[str]]:
        """Process spot price data into lists of timestamps and prices."""
        if not data:
            return [], [], []

        # Sort by timestamp
        sorted_data = sorted(data, key=lambda x: parser.parse(x['Timestamp']) if isinstance(x['Timestamp'], str) else x['Timestamp'])

        timestamps = []
        prices = []
        zones = []

        target_date = datetime.now(timezone.utc) - timedelta(days=self.config.days)

        for item in sorted_data:
            timestamp = parser.parse(item['Timestamp']) if isinstance(item['Timestamp'], str) else item['Timestamp']
            if timestamp >= target_date:
                timestamps.append(timestamp)
                prices.append(float(item['SpotPrice']))
                zones.append(item['AvailabilityZone'])

        return timestamps, prices, zones

    def calculate_region_price(self, timestamps: List[datetime], prices: List[float], zones: List[str]) -> Tuple[List[datetime], List[float]]:
        """Calculate representative prices for a region using median to handle outliers."""
        # Group data by timestamp
        timestamp_prices = {}
        for t, p, z in zip(timestamps, prices, zones):
            if t not in timestamp_prices:
                timestamp_prices[t] = []
            timestamp_prices[t].append(p)

        # For each timestamp, calculate median of available prices
        sorted_timestamps = sorted(timestamp_prices.keys())
        final_prices = []
        for t in sorted_timestamps:
            prices_at_t = timestamp_prices[t]
            median_price = sorted(prices_at_t)[len(prices_at_t)//2]
            final_prices.append(median_price)

        return sorted_timestamps, final_prices

    def analyze_and_display(self) -> None:
        """Main analysis and display function."""
        try:
            # Set detailed view automatically if only one region
            if len(self.config.regions) == 1:
                self.config.detailed = True

            if not self.config.json_mode:
                self.start_loading_animation()

            # Validate regions
            available_regions = self.fetch_available_regions()
            for region in self.config.regions:
                if region not in available_regions:
                    if self.config.json_mode:
                        sys.exit(1)
                    print(f"{RED}Error: '{region}' is not a valid AWS region.{RESET}\n")
                    print(f"{YELLOW}Valid regions are:{RESET}")
                    for valid_region in available_regions:
                        print(f" - {valid_region}")
                    return

            # Fetch and process data
            region_data = {}
            regions_with_data = []
            for region in self.config.regions:
                logging.info(f"Fetching data for region: {region}")
                spot_price_data = self.fetch_spot_price_history(region)
                if not spot_price_data:
                    if not self.config.json_mode:
                        print(f"{YELLOW}Warning: No spot price data available for instance type "
                              f"'{self.config.instance_type}' in region '{region}'{RESET}")
                    continue

                timestamps, prices, zones = self.process_spot_price_data(spot_price_data)
                if not prices:
                    if not self.config.json_mode:
                        print(f"{YELLOW}Warning: No prices found in the last {self.config.days} days "
                              f"for '{self.config.instance_type}' in region '{region}'{RESET}")
                    continue

                region_data[region] = (timestamps, prices, zones)
                regions_with_data.append(region)

            if not regions_with_data:
                if self.config.json_mode:
                    sys.exit(1)
                print(f"\n{RED}Error: No spot price data available for instance type "
                      f"'{self.config.instance_type}' in any of the specified regions.{RESET}")
                return

            # Stop loading animation before displaying results
            if not self.config.json_mode:
                self.stop_loading_animation()

                print(f"\n{BLUE}{'-'*80}{RESET}")
                print(f"{BOLD}EC2 Spot Price History - {self.config.instance_type}{RESET}")
                print(f"{CYAN}Last {self.config.days} days of price data{RESET}")
                print(f"{BLUE}{'-'*80}{RESET}\n")

            best_price = float('inf')
            best_price_region = None
            best_price_zone = None
            best_price_timestamp = None

            for region in regions_with_data:
                timestamps, prices, zones = region_data[region]

                if not self.config.json_mode:
                    print(f"\n{YELLOW}{'-'*40}{RESET}")
                    print(f"{BOLD}Region: {CYAN}{region}{RESET}")
                    print(f"{YELLOW}{'-'*40}{RESET}")

                    for timestamp, price, zone in zip(timestamps, prices, zones):
                        print(f"{GREEN}{timestamp.strftime('%Y-%m-%d %H:%M:%S')}  ${price:.5f}  {CYAN}{zone}{RESET}")

                    average_price = sum(prices) / len(prices)
                    latest_price = prices[-1]
                    latest_zone = zones[-1]

                    print(f"\n{BOLD}Summary for {region}:{RESET}")
                    print(f"{CYAN}{'Average Price:':<15}{RESET} ${average_price:.5f}")
                    print(f"{CYAN}{'Latest Price:':<15}{RESET} ${latest_price:.5f} in {latest_zone}")
                    print(f"{YELLOW}{'-'*40}{RESET}")

                if prices[-1] < best_price or (prices[-1] == best_price and timestamps[-1] > best_price_timestamp):
                    best_price = prices[-1]
                    best_price_region = region
                    best_price_zone = zones[-1]
                    best_price_timestamp = timestamps[-1]

            if best_price_region:
                if self.config.json_mode:
                    result = {
                        "lowestPrice": float(f"{best_price:.5f}"),
                        "availabilityZone": best_price_zone,
                        "region": best_price_region,
                        "instanceType": self.config.instance_type,
                        "lastUpdated": best_price_timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    }
                    print(json.dumps(result, indent=2))
                else:
                    # Collect latest prices from all zones
                    az_latest_prices = {}  # Dictionary to store latest price per AZ
                    for region in regions_with_data:
                        timestamps, prices, zones = region_data[region]
                        for i in range(len(prices)):
                            zone = zones[i]
                            # Update only if this is a more recent price for this AZ
                            if zone not in az_latest_prices or timestamps[i] > az_latest_prices[zone]['timestamp']:
                                az_latest_prices[zone] = {
                                    'price': prices[i],
                                    'timestamp': timestamps[i],
                                    'region': region
                                }
                    
                    # Convert dictionary to list and sort by price (ascending) and timestamp (descending)
                    sorted_zones = [
                        {'zone': zone, 'price': info['price'], 'timestamp': info['timestamp'], 'region': info['region']}
                        for zone, info in az_latest_prices.items()
                    ]
                    sorted_zones.sort(key=lambda x: (
                        x['price'],                    # First by price (ascending)
                        -x['timestamp'].timestamp(),   # Then by timestamp (newest first)
                        x['zone']                     # Then by AZ name (alphabetically)
                    ))
                    
                    # Display ranking
                    print(f"\n{BOLD}Availability Zone Ranking (Latest Prices){RESET}")
                    print(f"{YELLOW}{'-'*80}{RESET}")
                    print(f"{BOLD}{'Price':<15} {'Availability Zone':<35} {'Last Updated':<30}{RESET}")
                    print(f"{YELLOW}{'-'*80}{RESET}")
                    
                    for zone_info in sorted_zones:
                        print(f"${zone_info['price']:<14.5f} {zone_info['zone']:<35} {zone_info['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
                    
                    print(f"{YELLOW}{'-'*80}{RESET}")

                    # Display best price after the ranking
                    print(f"\n{BLUE}{'='*80}{RESET}")
                    print(f"{BOLD}Best current price for {self.config.instance_type}:{RESET}")
                    # Use the first entry from sorted_zones since it's already sorted by price, timestamp, and AZ name
                    best_zone_info = sorted_zones[0]
                    print(f"${best_zone_info['price']:.5f} in {best_zone_info['zone']} ({best_zone_info['region']})")
                    print(f"Last updated: {best_zone_info['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"{BLUE}{'='*80}{RESET}")

                    if not self.config.no_graph:
                        if not self.config.json_mode:
                            print("\nOpening price comparison graph...")
                        self.plot_spot_prices(region_data)

        except AWSError as e:
            logging.error(str(e))
            if self.config.json_mode:
                sys.exit(1)
            print(f"\n{RED}Error: {str(e)}{RESET}")
            if e.help_text:
                print(e.help_text)
            sys.exit(1)
        except KeyboardInterrupt:
            if not self.config.json_mode:
                print(f"\n\n{GREEN}Bye!{RESET}")
            sys.exit(0)
        except Exception as e:
            logging.error(f"Unexpected error: {str(e)}")
            if self.config.json_mode:
                sys.exit(1)
            print(f"\n{RED}Error: {str(e)}{RESET}")
            print(f"\n{YELLOW}To fix AWS credentials issues:{RESET}")
            print(f"1. Configure AWS CLI: {GREEN}aws configure{RESET}")
            print(f"2. Or specify a profile: {GREEN}--profile your-profile-name{RESET}")
            print(f"3. Make sure your credentials are valid and not expired")
            print(f"4. For SSO profiles, run: {GREEN}aws sso login --profile your-profile-name{RESET}")
            sys.exit(1)
        finally:
            if not self.config.json_mode:
                self.stop_loading_animation()

    def plot_spot_prices(self, region_data: Dict[str, Tuple[List[datetime], List[float], List[str]]]) -> None:
        """Plot spot prices for all regions."""
        if not self.config.json_mode:
            plt.figure(figsize=(15, 8))
            plt.grid(True, linestyle='--', linewidth=0.5, alpha=0.3, color='gray')

            colors_pool = [
                '#FF0000', '#0000FF', '#00CC00', '#FF00FF', '#FFA500',
                '#800080', '#008B8B', '#FFD700', '#4B0082', '#FF4500',
                '#2E8B57', '#9370DB', '#20B2AA', '#FF69B4', '#CD853F',
                '#00CED1', '#FF8C00', '#BA55D3', '#32CD32', '#8B0000'
            ]

            line_styles = ['-', '--', ':', '-.']

            # Returns a unique combination of color and line style based on index
            def get_unique_style(idx, total):
                color_idx = idx % len(colors_pool)
                style_idx = (idx // len(colors_pool)) % len(line_styles)
                return colors_pool[color_idx], line_styles[style_idx]

            legend_elements = []
            all_zones = set()
            for region in region_data.values():
                all_zones.update(region[2])

            for region_idx, (region, (timestamps, prices, zones)) in enumerate(region_data.items()):
                if timestamps and prices:
                    if self.config.detailed:
                        # Group data by AZ for detailed view
                        az_data = {}
                        for t, p, z in zip(timestamps, prices, zones):
                            if z not in az_data:
                                az_data[z] = {'timestamps': [], 'prices': []}
                            az_data[z]['timestamps'].append(t)
                            az_data[z]['prices'].append(p)

                        for az_idx, (az, data) in enumerate(sorted(az_data.items())):
                            global_idx = list(sorted(all_zones)).index(az)
                            color, style = get_unique_style(global_idx, len(all_zones))

                            line = plt.plot(data['timestamps'],
                                          data['prices'],
                                          marker='o',
                                          linestyle=style,
                                          color=color,
                                          markersize=4,
                                          label=f"{region}/{az}",
                                          linewidth=1.5)[0]
                            legend_elements.append(line)
                    else:
                        avg_timestamps, avg_prices = self.calculate_region_price(timestamps, prices, zones)
                        color, style = get_unique_style(region_idx, len(region_data))

                        line = plt.plot(avg_timestamps, avg_prices,
                                marker='o',
                                linestyle=style,
                                color=color,
                                markersize=4,
                                label=region,
                                linewidth=2)[0]
                        legend_elements.append(line)

            plt.title(f'AWS EC2 Spot Prices Comparison for {self.config.instance_type}')
            plt.xlabel('Timestamp')
            plt.ylabel('Price ($)')

            # Adjust legend layout based on number of items
            num_items = len(legend_elements)
            if num_items > 6:
                # Use more columns and compact spacing for many items
                ncol = min(max(4, num_items // 2), 8)  # Between 4 and 8 columns
                plt.legend(handles=legend_elements,
                          loc='upper center',
                          bbox_to_anchor=(0.5, -0.15),
                          ncol=ncol,
                          fontsize='x-small',
                          columnspacing=0.8,
                          handlelength=1.0,
                          handletextpad=0.4,
                          borderaxespad=0.2)
                plt.subplots_adjust(bottom=0.25)
            else:
                plt.legend(handles=legend_elements, loc='center right', fontsize='small')

            plt.xticks(rotation=45)

            # Rotate and align the tick labels so they look better
            plt.gcf().autofmt_xdate()

            plt.show(block=False)
            input("\nPress Enter to exit...")
            plt.close()
            print(f"\n{GREEN}Bye!{RESET}")

    def start_loading_animation(self) -> None:
        """Start the loading animation."""
        if not self.config.json_mode:
            self.loading = True
            self.loading_thread = threading.Thread(target=self._animate_loading)
            self.loading_thread.daemon = True
            self.loading_thread.start()

    def stop_loading_animation(self) -> None:
        """Stop the loading animation."""
        if not self.config.json_mode:
            self.loading = False
            if self.loading_thread:
                self.loading_thread.join()
                print('\r', end='')  # Clear the loading line
                sys.stdout.flush()

    def _animate_loading(self) -> None:
        """Animate the loading indicator."""
        spinner = ['|', '/', '-', '\\']
        idx = 0
        while self.loading:
            print(f'\rFetching data {spinner[idx]} ', end='', flush=True)
            idx = (idx + 1) % len(spinner)
            time.sleep(0.1)

def main():
    """Main entry point of the script."""
    parser = argparse.ArgumentParser(
        description='Fetch and plot AWS EC2 spot prices.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              %(prog)s                                          # Show prices for t3.medium in ap-south-1
              %(prog)s --days 7 --regions us-east-1            # Show last 7 days for us-east-1
              %(prog)s --instance-type c5.xlarge               # Show prices for c5.xlarge
              %(prog)s --regions us-east-1,us-west-2           # Compare prices across regions
              %(prog)s --regions all                           # Compare prices across all regions
              %(prog)s --profile my-aws-profile                # Use specific AWS profile
              %(prog)s --detailed                              # Show individual AZ prices
              %(prog)s --days 30 --regions eu-west-1,us-east-1 # Last 30 days in multiple regions
              %(prog)s --json                                  # Output JSON data for programmatic use
              %(prog)s --no-graph                              # Do not display the price graph
              %(prog)s -z us-east-1a                           # Filter by availability zone
        """)
    )

    parser.add_argument('--days', type=int, default=DEFAULT_DAYS,
                      help=f'Number of days to show in the graph (default: {DEFAULT_DAYS})')
    parser.add_argument('--instance-type', type=str, default=DEFAULT_INSTANCE_TYPE,
                      dest='instance_type',
                      help=f'EC2 instance type (default: {DEFAULT_INSTANCE_TYPE})')
    parser.add_argument('--regions', type=str, default=DEFAULT_REGION,
                      help=f'Comma-separated list of AWS regions or "all" (default: {DEFAULT_REGION})')
    parser.add_argument('--profile', type=str, default=DEFAULT_PROFILE,
                      help=f'AWS profile name (default: {DEFAULT_PROFILE})')
    parser.add_argument('--detailed', action='store_true',
                      help='Show all availability zones (default: show only cheapest AZ per region)')
    parser.add_argument('--json', action='store_true',
                      help='Output results in JSON format')
    parser.add_argument('--no-graph', action='store_true',
                      help='Do not display the price graph')
    parser.add_argument('-z', '--availability-zone', 
                       help='Specific availability zone to search in (e.g., us-east-1a)',
                       type=str)

    try:
        args = parser.parse_args()

        # Configure logging based on mode
        log_level = logging.ERROR if args.json else logging.INFO
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        config = SpotPriceConfig(
            days=args.days,
            instance_type=args.instance_type,
            regions=parse_regions(args.regions, args.profile),
            profile=args.profile,
            detailed=args.detailed,
            json_mode=args.json,
            no_graph=args.no_graph,
            availability_zone=args.availability_zone
        )

        if config.days <= 0:
            print(f"Error: Number of days must be positive")
            sys.exit(1)

        analyzer = SpotPriceAnalyzer(config)
        analyzer.analyze_and_display()

    except ValueError as e:
        logging.error(str(e))
        sys.exit(1)
    except AWSError as e:
        logging.error(e.message)
        if e.help_text:
            print(e.help_text)
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n\nBye!")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        print(f"\nError: {str(e)}")
        print(f"\nTo fix AWS credentials issues:")
        print(f"1. Configure AWS CLI: aws configure")
        print(f"2. Or specify a profile: --profile your-profile-name")
        print(f"3. Make sure your credentials are valid and not expired")
        print(f"4. For SSO profiles, run: aws sso login --profile your-profile-name")
        sys.exit(1)

if __name__ == "__main__":
    main()
