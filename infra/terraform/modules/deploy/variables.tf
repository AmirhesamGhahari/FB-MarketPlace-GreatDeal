variable "app_name" {
  type = string
}

variable "region" {
  type = string
}

variable "github_owner" {
  type = string
}

variable "github_repo" {
  type = string
}

variable "github_branch" {
  type    = string
  default = "main"
}

variable "connection_arn" {
  description = "The CodeStar connection to GitHub that the data-pipeline CodePipeline already uses (authorized once in the console)"
  type        = string
}

variable "artifact_bucket_name" {
  description = "S3 bucket where CodePipeline keeps the source zip (shared with the data-pipeline CodePipeline)"
  type        = string
}

variable "artifact_bucket_arn" {
  type = string
}

variable "api_function_name" {
  type = string
}

variable "api_function_arn" {
  type = string
}

variable "web_bucket_name" {
  type = string
}

variable "web_bucket_arn" {
  type = string
}

variable "cloudfront_distribution_id" {
  type = string
}

variable "site_live" {
  description = "false: automatic website builds are the hidden version (noindex, robots.txt Disallow). true: the version Google may index (launch switch)."
  type        = bool
  default     = false
}
