# Deal digest emails sent by the notify stage (published from the ECS task).
resource "aws_sns_topic" "deal_alerts" {
  name = "${var.app_name}-deal-alerts"
}

resource "aws_sns_topic_subscription" "deal_alerts_email" {
  topic_arn = aws_sns_topic.deal_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
