variable "region" {
  description = "AWS region"
  type        = string
  default     = "ca-central-1"
}

variable "app_name" {
  description = "Application name used for resource naming"
  type        = string
  default     = "fb-marketplace-greatdeals"
}

variable "apify_token_secret_arn" {
  description = "ARN of an existing Secrets Manager secret containing the Apify API token"
  type        = string
}

variable "gemini_api_key" {
  description = "Google Gemini API key"
  type        = string
  sensitive   = true
}

variable "github_owner" {
  description = "GitHub username or organization"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name, without the owner prefix"
  type        = string
}

variable "github_branch" {
  description = "Branch that triggers the CI/CD pipeline"
  type        = string
  default     = "main"
}

variable "category_configs" {
  description = "List of config names to scrape on each run (YAML filename without .yaml)"
  type        = list(string)
  default     = ["iphone"]
}
