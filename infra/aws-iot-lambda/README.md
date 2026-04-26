# AWS IoT Core + Lambda Terraform

This Terraform stack deploys:

- One Lambda function that receives respiration payloads from AWS IoT Core
- One IoT Topic Rule forwarding MQTT topics to Lambda
- IAM role + logs permissions for Lambda

## Prerequisites

- Terraform >= 1.6
- AWS credentials configured locally (`aws configure`)
- Existing AWS IoT Core endpoint and device certificate for your Jetson/edge publisher

## Usage

1. Copy variables template:
   - `cp terraform.tfvars.example terraform.tfvars`
2. Adjust `terraform.tfvars` values
3. Deploy:
   - `terraform init`
   - `terraform plan`
   - `terraform apply`

## Connect Edge MQTT To AWS IoT Core

Use AWS IoT endpoint as broker and provide the device certificate/key/CA in your MQTT client.
Current edge MQTT module already supports environment-driven broker config; update these values on Jetson:

- `MQTT_BROKER`
- `MQTT_PORT`
- `MQTT_USERNAME` (optional for non-certificate brokers)
- `MQTT_PASSWORD` (optional for non-certificate brokers)

## Telegram Alert Integration (Optional)

Set `telegram_webhook_url` in `terraform.tfvars`.
Lambda triggers alerts when BPM is below `alert_bpm_low` or above `alert_bpm_high`.
