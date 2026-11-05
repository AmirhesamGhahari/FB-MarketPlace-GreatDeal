# Website API: FastAPI on Lambda (Mangum) inside the VPC, behind an API Gateway HTTP API.
# The package folder is built by api/build_lambda.sh before `terraform apply`.

data "archive_file" "api" {
  type        = "zip"
  source_dir  = var.package_dir
  output_path = "${path.module}/api.zip"
}

resource "aws_iam_role" "api" {
  name = "${var.app_name}-api-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "api_vpc" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${var.app_name}-api"
  retention_in_days = 14
}

resource "aws_lambda_function" "api" {
  function_name    = "${var.app_name}-api"
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  role             = aws_iam_role.api.arn
  handler          = "fb_marketplace_api.main.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  memory_size      = var.memory_size
  timeout          = var.timeout

  reserved_concurrent_executions = var.reserved_concurrency

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.security_group_id]
  }

  environment {
    variables = {
      API_DATABASE_URL = "postgresql+psycopg://${urlencode(var.db_reader_username)}:${urlencode(var.db_reader_password)}@${var.db_host}:${var.db_port}/${var.db_name}?sslmode=require"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.api,
    aws_iam_role_policy_attachment.api_vpc,
  ]
}

# ── API Gateway (HTTP API): one catch-all route to the Lambda ────────────────

resource "aws_apigatewayv2_api" "api" {
  name          = "${var.app_name}-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.throttle_rate_limit
    throttling_burst_limit = var.throttle_burst_limit
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}
