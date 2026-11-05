output "distribution_id" {
  value = aws_cloudfront_distribution.main.id
}

output "domain_name" {
  description = "Public address of the site (https://<this>)"
  value       = aws_cloudfront_distribution.main.domain_name
}
