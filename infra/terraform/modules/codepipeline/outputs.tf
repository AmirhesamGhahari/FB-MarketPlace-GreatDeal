output "pipeline_name" {
  value = aws_codepipeline.main.name
}

output "connection_arn" {
  description = "Authorize this connection in AWS console → Developer Tools → Connections after first apply"
  value       = aws_codestarconnections_connection.github.arn
}

output "artifact_bucket_name" {
  description = "Also used by the website and API deploy pipelines (modules/deploy)"
  value       = aws_s3_bucket.artifacts.bucket
}

output "artifact_bucket_arn" {
  value = aws_s3_bucket.artifacts.arn
}
