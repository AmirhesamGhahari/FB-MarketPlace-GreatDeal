resource "aws_athena_workgroup" "main" {
  name = var.app_name

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = false

    result_configuration {
      output_location = "s3://${var.results_bucket}/athena-results/"
    }
  }
}
