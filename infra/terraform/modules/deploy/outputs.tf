output "api_project_name" {
  value = aws_codebuild_project.api.name
}

output "web_project_name" {
  value = aws_codebuild_project.web.name
}

output "api_pipeline_name" {
  value = aws_codepipeline.api.name
}

output "web_pipeline_name" {
  description = "Started by the Step Functions run after dbt, and by a GitHub push that touches web/"
  value       = aws_codepipeline.web.name
}

output "web_pipeline_arn" {
  value = aws_codepipeline.web.arn
}
