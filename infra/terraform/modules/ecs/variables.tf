variable "app_name" {
  type = string
}

variable "region" {
  type = string
}

variable "ecr_repository_url" {
  type = string
}

variable "db_url_secret_arn" {
  type = string
}

variable "apify_token_secret_arn" {
  type = string
}

variable "gemini_api_key_secret_arn" {
  type = string
}

variable "deal_alerts_topic_arn" {
  description = "SNS topic the notify stage publishes deal digests to (email channel)"
  type        = string
}

