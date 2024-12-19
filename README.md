# AWS EC2 Spot Price Tracker

This Python script fetches and plots the historical spot prices of AWS EC2 instances across multiple regions. It utilizes the Boto3 library to interact with AWS services and Matplotlib for data visualization.

## Features

- Fetches spot price history for a specified EC2 instance type across various AWS regions.
- Allows filtering of data based on the number of days.
- Displays prices in a graph for easy comparison.
- Outputs average and latest prices for each region.
- Identifies the best current spot price across specified regions.

## Prerequisites

- Python 3.x
- AWS account with appropriate permissions to access EC2 spot price data.
- AWS CLI configured with a profile that has access to the EC2 service.

## Installation

1. **Clone the repository:**

   ```bash
   git clone <repository-url>
   cd <repository-folder>
   ```

2. **Install required packages:**

   You will need to install the following Python packages:

   ```bash
   pip install boto3 pandas matplotlib python-dateutil
   ```

## Usage

Run the script using the following command:

```bash
python spotter.py [days] [regions] --instance_type [instance_type] --profile [profile_name]
```

- **days**: (Optional) Number of days to show in the graph (default: 30).
- **regions**: (Optional) AWS region(s) to fetch data from (default: `ap-south-1`). Use `all` to fetch data from all available regions.
- **--instance_type**: (Optional) Specify the EC2 instance type (default: `t3.medium`).
- **--profile**: (Optional) Specify the AWS profile name (default: `default`).

### Example Commands

1. Fetch spot prices for the default instance type in the default region for the last 30 days:

   ```bash
   python spotter.py
   ```

2. Fetch spot prices for `t3.micro` in the `us-east-1` and `eu-west-1` regions for the last 14 days:

   ```bash
   python spotter.py 14 us-east-1 eu-west-1 --instance_type t3.micro
   ```

3. Fetch spot prices for all regions for the last 7 days using the default profile:

   ```bash
   python spotter.py 7 all
   ```

4. Fetch spot prices for the last 30 days using a specific profile:

   ```bash
   python spotter.py --profile my-profile
   ```

## Output

The script will print the date and spot prices for each specified region to the console. It will also display the average and latest prices, as well as the best current price across regions.

A plot will be generated showing the spot prices over time for the specified instance type across the selected regions.

## Loading Animation

While data is being fetched, a loading animation will be displayed in the terminal to indicate progress.

## Notes

- Ensure your AWS credentials are configured correctly in the AWS CLI. You can set up your profile using:

   ```bash
   aws configure --profile an-dev-sso
   ```

- The script uses the `default` profile by default. Change this in the script if you use a different profile name.

## License

This project is licensed under the MIT License. See the LICENSE file for details.

You can modify the content as needed to fit your project and preferences!
