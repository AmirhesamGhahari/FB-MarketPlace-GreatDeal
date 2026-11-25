# The site's own address: a Route 53 zone (the "phone book" for the domain), an HTTPS certificate, and the records that point
# the domain at CloudFront. CloudFront only accepts certificates from us-east-1, hence the second provider (aws.us_east_1).
terraform {
  required_providers {
    aws = {
      source                = "hashicorp/aws"
      configuration_aliases = [aws.us_east_1]
    }
  }
}

locals {
  www_name = "www.${var.domain_name}"
  # The fixed hosted zone id that every CloudFront distribution uses for alias records.
  cloudfront_zone_id = "Z2FDTNDATAQYW2"
}

resource "aws_route53_zone" "main" {
  name    = var.domain_name
  comment = "${var.app_name} website"
}

# Certificate for the bare domain and www, proven by DNS records in the zone above.
resource "aws_acm_certificate" "site" {
  provider                  = aws.us_east_1
  domain_name               = var.domain_name
  subject_alternative_names = [local.www_name]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "validation" {
  for_each = {
    for option in aws_acm_certificate.site.domain_validation_options : option.domain_name => {
      name   = option.resource_record_name
      type   = option.resource_record_type
      record = option.resource_record_value
    }
  }

  zone_id         = aws_route53_zone.main.zone_id
  name            = each.value.name
  type            = each.value.type
  ttl             = 60
  records         = [each.value.record]
  allow_overwrite = true
}

# Waits until the certificate is issued. This only works once the domain's nameservers (at the registrar) point at the zone.
resource "aws_acm_certificate_validation" "site" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.site.arn
  validation_record_fqdns = [for record in aws_route53_record.validation : record.fqdn]
}

# techdealradar.ca and www.techdealradar.ca both go to CloudFront (the www name is redirected to the bare name by the
# CloudFront function), over IPv4 (A) and IPv6 (AAAA).
resource "aws_route53_record" "alias" {
  for_each = {
    for pair in setproduct(["apex", "www"], ["A", "AAAA"]) : "${pair[0]}-${pair[1]}" => {
      name = pair[0] == "apex" ? var.domain_name : local.www_name
      type = pair[1]
    }
  }

  zone_id = aws_route53_zone.main.zone_id
  name    = each.value.name
  type    = each.value.type

  alias {
    name                   = var.cloudfront_domain_name
    zone_id                = local.cloudfront_zone_id
    evaluate_target_health = false
  }
}

# Any other records the domain needs (email forwarding MX and SPF records, search engine verification, ...). name "@" is the
# bare domain.
resource "aws_route53_record" "extra" {
  for_each = { for record in var.extra_records : "${record.name}-${record.type}" => record }

  zone_id = aws_route53_zone.main.zone_id
  name    = each.value.name == "@" ? var.domain_name : "${each.value.name}.${var.domain_name}"
  type    = each.value.type
  ttl     = each.value.ttl
  records = each.value.values
}
