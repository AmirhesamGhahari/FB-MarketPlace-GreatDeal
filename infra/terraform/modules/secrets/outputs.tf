output "db_url_secret_arn" {
  value = aws_secretsmanager_secret.db_url.arn
}

output "gemini_api_key_secret_arn" {
  value = aws_secretsmanager_secret.gemini_api_key.arn
}
