# AWS Spotter: EC2 Spot Price Tracker

This Python script fetches and plots the historical spot prices of AWS EC2 instances across multiple regions. It utilizes the Boto3 library to interact with AWS services and Matplotlib for data visualization.

   ```bash
   # Compare prices between major regions for a compute-optimized instance
   python aws_spotter.py --regions us-east-1,eu-west-1,ap-south-1 --instance-type c5.xlarge
   ```

   ![image](https://github.com/user-attachments/assets/3e0abcab-e334-4366-a8da-dd15f7016936)

   Shows the best (lowest) price between the selected regions:
 
   ![image](https://github.com/user-attachments/assets/f48f503c-33b8-4015-ab50-aebb18dbb583)

   Optional output in JSON format with --json parameter. Ideal for automation:
   
   ```json
   {
     "lowestPrice": 0.01850,
     "availabilityZone": "us-west-1a",
     "region": "us-west-1",
     "instanceType": "t3a.medium",
     "lastUpdated": "2024-12-19 22:31:26"
   }
   ```

## Features

- Fetches spot price history for any EC2 instance type across AWS regions
- Interactive mode with visual graphs and detailed price information
- JSON output mode for programmatic use and automation
- Supports single or multiple region comparison
- Displays current lowest price across all specified regions
- Shows price trends with interactive matplotlib graphs
- Supports AWS profiles for different credentials

## Prerequisites

- Python 3.x
- AWS account with EC2 spot price data access permissions
- AWS CLI configured with appropriate credentials

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd spot-pricing-graph
   ```

2. Install required packages:
   ```bash
   pip install boto3 matplotlib pandas
   ```

## Usage

The script can be run in two modes: interactive (default) with graphs and detailed output, or JSON mode for automation.

### Basic Command Structure

```bash
python aws_spotter.py [OPTIONS]
```

### Options

- `--days NUMBER`: Number of days of price history (default: 30)
- `--instance-type TYPE`: EC2 instance type (default: t3.medium)
- `--regions REGIONS`: AWS regions to analyze. Can be:
  - Single region: `us-east-1`
  - Multiple regions (comma-separated, no spaces): `us-east-1,eu-west-1,ap-south-1`
  - All regions: `all`
- `--profile NAME`: AWS profile name (default: default)
- `--json`: Output results in JSON format for automation
- `--detailed`: Show individual Availability Zone prices (automatically enabled for single region)

### Examples and Use Cases

- **Find the cheapest region for your instance type:**
   ```bash
   # Search across all AWS regions for the lowest t3a.medium spot price
   python aws_spotter.py --regions all --instance-type t3a.medium
   ```

- **Quick price check for automation. Find the chepeast AZ across all the regions:**
   ```bash
   # Get JSON output for automated decision making
   python aws_spotter.py --regions all --instance-type t3.nano --json 
   ```
   
   Output:
   ```json
   {
     "lowestPrice": 0.0011,
     "availabilityZone": "ap-northeast-2c",
     "region": "ap-northeast-2",
     "instanceType": "t3.nano",
     "lastUpdated": "2024-12-20 01:31:27"
   }
   ```

- **Compare specific regions:**
   ```bash
   # Compare prices between major regions for a compute-optimized instance
   python aws_spotter.py --regions us-east-1,eu-west-1,ap-south-1 --instance-type c5.xlarge
   ```

- **Historical price analysis:**
   ```bash
   # Check price trends over the last 90 days
   python aws_spotter.py --days 90 --regions us-east-1 --instance-type m5.xlarge
   ```

- **Multi-region deployment planning:**
   ```bash
   # Compare prices in regions with low latency to Asia
   python aws_spotter.py --regions ap-southeast-1,ap-northeast-1,ap-south-1 --instance-type r5.2xlarge
   ```

- **Quick current price check:**
    ```bash
    # Get just today's prices for a specific region
    python aws_spotter.py --days 1 --regions us-east-1 --instance-type t3.medium
    ```

- **Analyze Availability Zones price trends in a single region:**
   ```bash
   # View detailed pricing across all AZs in us-east-1
   python aws_spotter.py --regions us-west-1 --detailed
   ```
   
   Example:
   ![image](https://github.com/user-attachments/assets/ea3002a9-87db-49e2-afb3-99446fed43ad)


The interactive mode provides visual graphs and detailed information, while the JSON mode is perfect for automation and scripting. Use `--detailed` when you need to see prices for individual Availability Zones, which is especially useful for high-availability deployments.

## Output Modes

### Interactive Mode (Default)
- Displays a graph comparing spot prices across selected regions
- Shows the current lowest price and its location
- Provides average and latest prices for each region
- When using `--detailed` or single region, shows prices per Availability Zone
- Interactive matplotlib graph with zoom and pan capabilities
- Press Enter to exit after viewing the graph

### JSON Mode
- Silent operation (no progress output)
- Returns only the lowest price information in JSON format
- Ideal for automation and scripting
- Exits with status code 1 on errors
- No graphs or visual elements

## Error Handling

- Validates AWS regions before processing
- Checks AWS credentials and provides helpful error messages
- Handles network issues gracefully
- Clear error messages for troubleshooting

## AWS Credentials

The script uses the AWS credentials configured in your system. You can:
1. Use the default profile: `aws configure`
2. Use a specific profile: `--profile your-profile-name`
3. For SSO profiles: `aws sso login --profile your-profile-name`

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
