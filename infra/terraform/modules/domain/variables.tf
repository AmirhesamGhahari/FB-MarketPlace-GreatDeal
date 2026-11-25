variable "app_name" {
  type = string
}

variable "domain_name" {
  description = "The bare domain, for example techdealradar.ca"
  type        = string
}

variable "cloudfront_domain_name" {
  description = "The distribution's own address (dxxxx.cloudfront.net), the target of the alias records"
  type        = string
}

variable "extra_records" {
  description = "More DNS records: name (\"@\" = the bare domain), type, ttl, values"
  type = list(object({
    name   = string
    type   = string
    ttl    = optional(number, 3600)
    values = list(string)
  }))
  default = []
}
