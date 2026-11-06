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
  description = "ARN of an existing Secrets Manager secret containing the Apify API token (from another AWS project)"
  type        = string
}

variable "gemini_api_key" {
  description = "Google Gemini API key"
  type        = string
  sensitive   = true
}

variable "db_master_username" {
  description = "Aurora master username"
  type        = string
  default     = "amir_ghahari"
}

variable "db_master_password" {
  description = "Aurora master password (min 8 chars)"
  type        = string
  sensitive   = true
}

variable "api_reader_password" {
  description = "Password of the read-only Postgres role web_serving_tables_reader used by the website API (set the same value in the database with ALTER ROLE; see api_front_end.md, Phase 4b)"
  type        = string
  sensitive   = true
}

variable "api_reserved_concurrency" {
  description = "Reserved Lambda concurrency for the website API (a cap and a guarantee; each running request holds one database connection); -1 = unreserved. The account quota is 1000 (AWS keeps 100 unreserved), so values up to 900 are possible."
  type        = number
  default     = 10
}

variable "db_name" {
  description = "Aurora database name"
  type        = string
  default     = "fb_marketplace_greatdeals"
}

variable "github_owner" {
  description = "GitHub username or organization (e.g. amirhesam)"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name, without the owner prefix (e.g. FB-MarketPlace-GreatDeals)"
  type        = string
}

variable "github_branch" {
  description = "Branch that triggers the CI/CD pipeline"
  type        = string
  default     = "main"
}

variable "category_configs" {
  description = "List of config names to scrape on each run (YAML filename without .yaml). Example: [\"iphone\", \"macbook\"]."
  type        = list(string)
  default     = ["iphone"]
}

variable "alert_email" {
  description = "Email address for deal alert emails (the SNS subscription must be confirmed by clicking the link AWS emails)"
  type        = string
}
