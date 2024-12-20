#!/usr/bin/env python3

from typing import List, Dict, Tuple, Optional
import boto3
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, timezone
import argparse
from dateutil.parser import isoparse
import threading
import time
import sys
import logging
import botocore
from dataclasses import dataclass
import textwrap

# Constants
DEFAULT_DAYS = 30
DEFAULT_INSTANCE_TYPE = 't3.medium'
DEFAULT_REGION = 'ap-south-1'
DEFAULT_PROFILE = 'default'
SPINNER_CHARS = ['|', '/', '-', '\\']
GRAPH_COLORS = ['blue', 'orange', 'green', 'red', 'purple', 'cyan', 'magenta', 
                'brown', 'pink', 'gray', 'olive', 'teal', 'navy', 'gold']

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

@dataclass
class SpotPriceConfig:
    """Configuration class for spot price analysis."""
    days: int = DEFAULT_DAYS
    instance_type: str = DEFAULT_INSTANCE_TYPE
    regions: List[str] = None
    profile: str = DEFAULT_PROFILE

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
            self.session = boto3.Session(profile_name=config.profile)
        except botocore.exceptions.ProfileNotFound:
            raise AWSError(
                f"AWS profile '{config.profile}' not found",
                help_text=(
                    "\nTo fix this:\n"
                    "1. Check your AWS credentials file (~/.aws/credentials)\n"
                    "2. Ensure the profile exists and is correctly configured\n"
                    "3. Available profiles can be found in ~/.aws/credentials\n"
                    "4. Use --profile <name> to specify a different profile"
                )
            )

    def fetch_available_regions(self) -> List[str]:
        """Fetch available AWS regions for EC2."""
        try:
            ec2_client = self.session.client('ec2')
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
            response = ec2_client.describe_spot_price_history(
                InstanceTypes=[self.config.instance_type],
                ProductDescriptions=["Linux/UNIX"],
                StartTime=datetime.now(timezone.utc) - timedelta(days=self.config.days),
            )
            return response['SpotPriceHistory']
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

    def process_spot_price_data(self, data: List[Dict]) -> Tuple[List[datetime], List[float]]:
        """Process raw spot price data into timestamps and prices."""
        if not data:
            return [], []

        prices = []
        timestamps = []
        target_date = datetime.now(timezone.utc) - timedelta(days=self.config.days)

        for entry in data:
            price = float(entry['SpotPrice'])
            timestamp = entry['Timestamp']
            if isinstance(timestamp, str):
                timestamp = isoparse(timestamp)

            if timestamp >= target_date:
                prices.append(price)
                timestamps.append(timestamp)

        return timestamps, prices

    def plot_spot_prices(self, region_data: Dict[str, Tuple[List[datetime], List[float]]]) -> None:
        """Plot spot prices for all regions."""
        plt.figure(figsize=(12, 6))
        
        for idx, (region, (timestamps, prices)) in enumerate(region_data.items()):
            if timestamps and prices:
                plt.plot(timestamps, prices, marker='o', linestyle='-', 
                        color=GRAPH_COLORS[idx % len(GRAPH_COLORS)], label=region)

        plt.title(f'AWS EC2 Spot Prices Comparison for {self.config.instance_type}')
        plt.xlabel('Timestamp')
        plt.ylabel('Spot Price ($)')
        plt.xticks(rotation=45)
        plt.grid()
        plt.legend()
        plt.tight_layout()
        
        plt.show(block=False)
        input("\nPress Enter to exit...")
        plt.close()
        print("\nBye!")

    def start_loading_animation(self) -> None:
        """Start the loading animation."""
        self.loading = True
        self.loading_thread = threading.Thread(target=self._loading_animation)
        self.loading_thread.daemon = True
        self.loading_thread.start()

    def stop_loading_animation(self) -> None:
        """Stop the loading animation."""
        self.loading = False
        if self.loading_thread and self.loading_thread.is_alive():
            self.loading_thread.join()
            sys.stdout.write('\r')
            sys.stdout.flush()

    def _loading_animation(self) -> None:
        """Display loading animation."""
        idx = 0
        while self.loading:
            sys.stdout.write(f'\rLoading data... {SPINNER_CHARS[idx]}')
            sys.stdout.flush()
            idx = (idx + 1) % len(SPINNER_CHARS)
            time.sleep(0.2)

    def analyze_and_display(self) -> None:
        """Main analysis and display function."""
        try:
            self.start_loading_animation()
            
            # Validate regions
            available_regions = self.fetch_available_regions()
            for region in self.config.regions:
                if region not in available_regions:
                    print(f"Error: '{region}' is not a valid AWS region.\n")
                    print("Valid regions are:")
                    for valid_region in available_regions:
                        print(f" - {valid_region}")
                    return

            # Fetch and process data
            region_data = {}
            for region in self.config.regions:
                logging.info(f"Fetching data for region: {region}")
                spot_price_data = self.fetch_spot_price_history(region)
                if not spot_price_data:
                    print(f"Error: No spot price data available for instance type "
                          f"'{self.config.instance_type}' in region '{region}'.")
                    return

                timestamps, prices = self.process_spot_price_data(spot_price_data)
                region_data[region] = (timestamps, prices)

            # Stop loading animation before displaying results
            self.stop_loading_animation()

            # Display results
            print(f"\nDate and Spot Prices for {self.config.instance_type}:")
            best_price = float('inf')
            best_price_region = None

            for region, (timestamps, prices) in region_data.items():
                if not prices:
                    print(f"\nRegion: {region} - No prices available")
                    continue

                print(f"\nRegion: {region}")
                for timestamp, price in zip(timestamps, prices):
                    print(f"{timestamp.strftime('%Y-%m-%d %H:%M:%S')} - ${price:.5f}")

                average_price = sum(prices) / len(prices)
                latest_price = prices[-1]
                print(f"Average Price: ${average_price:.5f}")
                print(f"Latest Price: ${latest_price:.5f}")

                if latest_price < best_price:
                    best_price = latest_price
                    best_price_region = region

            if best_price_region:
                print(f"\nBest current Price for {self.config.instance_type}: "
                      f"${best_price:.5f} in region: {best_price_region}")

            print("\nOpening price comparison graph...")
            self.plot_spot_prices(region_data)

        except AWSError as e:
            logging.error(str(e))
            sys.exit(1)
        except KeyboardInterrupt:
            print("\n\nBye!")  # Graceful exit message
            sys.exit(0)
        except Exception as e:
            logging.error(f"Unexpected error: {str(e)}")
            sys.exit(1)
        finally:
            self.stop_loading_animation()

def main():
    """Main entry point of the script."""
    parser = argparse.ArgumentParser(
        description='Fetch and plot AWS EC2 spot prices.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              %(prog)s                               # Show prices for t3.medium in ap-south-1
              %(prog)s 7 us-east-1                   # Show last 7 days for us-east-1
              %(prog)s --instance_type c5.xlarge     # Show prices for c5.xlarge
              %(prog)s 30 us-east-1 us-west-2        # Compare prices across regions
              %(prog)s --profile my-aws-profile      # Use specific AWS profile
        """)
    )
    
    parser.add_argument('days', type=int, nargs='?', default=DEFAULT_DAYS,
                      help=f'Number of days to show in the graph (default: {DEFAULT_DAYS})')
    parser.add_argument('regions', type=str, nargs='*', default=[DEFAULT_REGION],
                      help=f'AWS region(s) (default: {DEFAULT_REGION})')
    parser.add_argument('--instance_type', type=str, default=DEFAULT_INSTANCE_TYPE,
                      help=f'EC2 instance type (default: {DEFAULT_INSTANCE_TYPE})')
    parser.add_argument('--profile', type=str, default=DEFAULT_PROFILE,
                      help=f'AWS profile name (default: {DEFAULT_PROFILE})')
    args = parser.parse_args()

    try:
        config = SpotPriceConfig(
            days=args.days,
            instance_type=args.instance_type,
            regions=args.regions,
            profile=args.profile
        )

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
        print("\n\nBye!")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
