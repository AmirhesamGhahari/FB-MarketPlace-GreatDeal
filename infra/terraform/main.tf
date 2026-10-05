module "networking" {
  source   = "./modules/networking"
  app_name = var.app_name
  region   = var.region
}

module "ecr" {
  source   = "./modules/ecr"
  app_name = var.app_name
}

module "aurora" {
  source             = "./modules/aurora"
  app_name           = var.app_name
  public_subnet_ids  = module.networking.public_subnet_ids
  aurora_sg_id       = module.networking.aurora_sg_id
  db_master_username = var.db_master_username
  db_master_password = var.db_master_password
  db_name            = var.db_name
}

module "secrets" {
  source             = "./modules/secrets"
  app_name           = var.app_name
  db_master_username = var.db_master_username
  db_master_password = var.db_master_password
  aurora_endpoint    = module.aurora.cluster_endpoint
  aurora_port        = module.aurora.cluster_port
  db_name            = var.db_name
  gemini_api_key     = var.gemini_api_key
}

module "ecs" {
  source                    = "./modules/ecs"
  app_name                  = var.app_name
  region                    = var.region
  ecr_repository_url        = module.ecr.repository_url
  db_url_secret_arn         = module.secrets.db_url_secret_arn
  apify_token_secret_arn    = var.apify_token_secret_arn
  gemini_api_key_secret_arn = module.secrets.gemini_api_key_secret_arn
}

module "scheduler" {
  source             = "./modules/scheduler"
  app_name           = var.app_name
  ecs_cluster_arn    = module.ecs.cluster_arn
  execution_role_arn = module.ecs.execution_role_arn
  task_role_arn      = module.ecs.task_role_arn
  public_subnet_ids  = module.networking.public_subnet_ids
  ecs_task_sg_id     = module.networking.ecs_task_sg_id
  category_configs   = var.category_configs
  lambda_source_dir  = "${path.module}/../lambda/fanout"
  task_family        = "${var.app_name}-pipeline"
}

module "codepipeline" {
  source             = "./modules/codepipeline"
  app_name           = var.app_name
  region             = var.region
  github_owner       = var.github_owner
  github_repo        = var.github_repo
  github_branch      = var.github_branch
  ecr_repository_url = module.ecr.repository_url
  ecr_repository_arn = module.ecr.repository_arn
  execution_role_arn = module.ecs.execution_role_arn
  task_role_arn      = module.ecs.task_role_arn
  task_family        = "${var.app_name}-pipeline"
}
