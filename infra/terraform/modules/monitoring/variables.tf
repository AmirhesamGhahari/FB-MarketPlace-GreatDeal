variable "app_name" {
  type = string
}

variable "alert_email" {
  description = "Address that receives the alarm emails (AWS sends one confirmation email that must be clicked once)"
  type        = string
}

variable "api_function_name" {
  description = "Website API Lambda function name (dimension of the Lambda alarms)"
  type        = string
}

variable "api_id" {
  description = "Website API Gateway HTTP API id (dimension of the API Gateway alarms)"
  type        = string
}
