output "api_url" {
  description = "API Gateway default endpoint (the Lambda sees paths like /v1/...)"
  value       = aws_apigatewayv2_api.api.api_endpoint
}

output "api_domain" {
  description = "API Gateway host name without https:// (the CloudFront origin domain)"
  value       = replace(aws_apigatewayv2_api.api.api_endpoint, "https://", "")
}

output "function_name" {
  value = aws_lambda_function.api.function_name
}

output "function_arn" {
  value = aws_lambda_function.api.arn
}
