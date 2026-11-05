output "ecr_repository_url" {
  description = "ECR repository URL (also available in CodeBuild as ECR_REPO_URL env var)"
  value       = module.ecr.repository_url
}

output "codepipeline_name" {
  value = module.codepipeline.pipeline_name
}

output "codestar_connection_arn" {
  description = "After first apply: open AWS console → Developer Tools → Connections → authorize this connection"
  value       = module.codepipeline.connection_arn
}

output "aurora_endpoint" {
  description = "Aurora cluster writer endpoint"
  value       = module.aurora.cluster_endpoint
}

output "aurora_port" {
  value = module.aurora.cluster_port
}

output "ecs_cluster_name" {
  value = module.ecs.cluster_name
}

output "task_definition_arn" {
  value = module.ecs.task_definition_arn
}

output "fanout_lambda_arn" {
  value = module.scheduler.lambda_arn
}

output "api_url" {
  description = "Website API Gateway endpoint (CloudFront will front it in Phase 4d)"
  value       = module.api.api_url
}

output "api_lambda_name" {
  value = module.api.function_name
}

output "site_url" {
  description = "Public site address (frontend at /, API under /api)"
  value       = "https://${module.cdn.domain_name}"
}

output "cloudfront_distribution_id" {
  description = "Needed by the pipeline to invalidate the cache after each run (Phase 6)"
  value       = module.cdn.distribution_id
}

output "web_bucket_name" {
  description = "Frontend bucket (Phase 5/6 deploys files here)"
  value       = module.web.bucket_id
}
