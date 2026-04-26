variable "aws_region" {
  type        = string
  description = "AWS region"
  default     = "us-east-1"
}

variable "project_prefix" {
  type        = string
  description = "Prefix used in Terraform-created resource names"
  default     = "respiration"
}

variable "lambda_function_name" {
  type        = string
  description = "Lambda name receiving IoT Core messages"
  default     = "respiration-iot-handler"
}

variable "iot_topic_filter" {
  type        = string
  description = "MQTT topic filter for the IoT Rule"
  default     = "respiration/#"
}

variable "telegram_webhook_url" {
  type        = string
  description = "Optional Telegram bot webhook endpoint"
  default     = ""
  sensitive   = true
}

variable "alert_bpm_low" {
  type        = number
  description = "Lower BPM threshold for alerts"
  default     = 5
}

variable "alert_bpm_high" {
  type        = number
  description = "Upper BPM threshold for alerts"
  default     = 30
}
