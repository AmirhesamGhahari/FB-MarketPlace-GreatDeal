variable "app_name" {
  type = string
}

variable "web_bucket_id" {
  type = string
}

variable "web_bucket_arn" {
  type = string
}

variable "web_bucket_regional_domain_name" {
  type = string
}

variable "api_domain" {
  description = "API Gateway host name without https://"
  type        = string
}

variable "price_class" {
  description = "PriceClass_100 = North America and Europe edge locations (cheapest)"
  type        = string
  default     = "PriceClass_100"
}

variable "api_max_ttl_seconds" {
  description = "Safety ceiling for API responses: caps whatever s-maxage the API sends (the API's own header is 6 h)"
  type        = number
  default     = 86400
}
