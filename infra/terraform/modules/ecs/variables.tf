variable "app_name" {
  type = string
}

variable "region" {
  type = string
}

variable "ecr_repository_url" {
  type = string
}

variable "apify_token_secret_arn" {
  type = string
}

variable "gemini_api_key_secret_arn" {
  type = string
}

variable "data_bucket_name" {
  type = string
}

variable "data_bucket_arn" {
  type = string
}

variable "athena_workgroup" {
  type = string
}
