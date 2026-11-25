output "name_servers" {
  description = "Paste these four into the registrar (Squarespace: DNS settings, custom nameservers)"
  value       = aws_route53_zone.main.name_servers
}

output "certificate_arn" {
  description = "The issued certificate (known only after DNS validation worked)"
  value       = aws_acm_certificate_validation.site.certificate_arn
}

output "zone_id" {
  value = aws_route53_zone.main.zone_id
}
