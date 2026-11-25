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

variable "aliases" {
  description = "The domain names that reach this distribution (empty = only the cloudfront.net address)"
  type        = list(string)
  default     = []
}

variable "certificate_arn" {
  description = "ACM certificate (us-east-1) for the aliases; empty = the default cloudfront.net certificate"
  type        = string
  default     = ""
}

variable "canonical_host" {
  description = "The main address the website redirects to (for example techdealradar.ca); empty = no host redirect"
  type        = string
  default     = ""
}

variable "redirect_hosts" {
  description = "Host names that are redirected permanently to canonical_host (for example www.techdealradar.ca)"
  type        = list(string)
  default     = []
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
