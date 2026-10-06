output "gemini_api_key_secret_arn" {
  value = aws_secretsmanager_secret.gemini_api_key.arn
}
