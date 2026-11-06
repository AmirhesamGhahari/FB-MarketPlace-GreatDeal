resource "aws_sns_topic" "alerts" {
  name = "${var.app_name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ── Alarm 1: the API Lambda threw an unhandled error ───────────────────────────
# Code bugs and crashes. A 503 the app returns on purpose is NOT counted here (see alarm 3).
resource "aws_cloudwatch_metric_alarm" "api_lambda_errors" {
  alarm_name          = "${var.app_name}-api-lambda-errors"
  alarm_description   = "The website API Lambda raised unhandled errors in 2 consecutive 5-minute windows. Check /aws/lambda/${var.app_name}-api"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    FunctionName = var.api_function_name
  }
}

# ── Alarm 2: slow requests ─────────────────────────────────────────────────────
# 95% of requests should finish well under the 28 s Lambda timeout; 20 s means the database is waking or struggling.
resource "aws_cloudwatch_metric_alarm" "api_lambda_duration" {
  alarm_name          = "${var.app_name}-api-lambda-slow"
  alarm_description   = "p95 duration of the website API Lambda above 20 s (timeout is 28 s) in 2 consecutive windows"
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = 20000 # milliseconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    FunctionName = var.api_function_name
  }
}

# ── Alarm 3: API Gateway returned a 5xx ────────────────────────────────────────
# Includes the 503 database_resuming / database_unavailable responses the app returns on purpose (the Lambda
# counts those as successful invocations), and Lambda failures or throttling seen by API Gateway.
resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${var.app_name}-api-5xx"
  alarm_description   = "API Gateway returned 5xx responses in 2 consecutive windows (database unreachable, Lambda failing or throttled)"
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    ApiId = var.api_id
    Stage = "$default"
  }
}

# ── Alarm 4: many 4xx responses ────────────────────────────────────────────────
# HTTP APIs have no separate 429 metric: throttled requests (429) are counted inside 4xx together with the API's own
# 404 and 422 answers. More than 20 in 5 minutes means the shared throttle is saturated or something is probing the API.
resource "aws_cloudwatch_metric_alarm" "api_4xx" {
  alarm_name          = "${var.app_name}-api-4xx-high"
  alarm_description   = "More than 20 client-error (4xx, includes 429 throttling) responses in each of 2 consecutive windows"
  namespace           = "AWS/ApiGateway"
  metric_name         = "4xx"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = 20
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    ApiId = var.api_id
    Stage = "$default"
  }
}
