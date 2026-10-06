resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.app_name}"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "main" {
  name = var.app_name
}

# Execution role — used by the ECS agent to pull images and inject secrets
resource "aws_iam_role" "execution" {
  name = "${var.app_name}-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution_base" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "secrets-read"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        var.apify_token_secret_arn,
        var.gemini_api_key_secret_arn,
      ]
    }]
  })
}

# Task role — what the running container itself is allowed to do
resource "aws_iam_role" "task" {
  name = "${var.app_name}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "task_s3_athena" {
  name = "s3-athena-glue-access"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [
          var.data_bucket_arn,
          "${var.data_bucket_arn}/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:StopQueryExecution",
          "athena:ListWorkGroups",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetTable",
          "glue:GetTables",
          "glue:GetPartition",
          "glue:GetPartitions",
          "glue:BatchCreatePartition",
          "glue:CreatePartition",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_ecs_task_definition" "pipeline" {
  family                   = "${var.app_name}-pipeline"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name      = "pipeline"
    image     = "${var.ecr_repository_url}:latest"
    essential = true

    # Default command shows help; Lambda always overrides this with the real subcommand
    command = ["--help"]

    environment = [
      { name = "S3_BUCKET",         value = var.data_bucket_name },
      { name = "AWS_REGION",        value = var.region },
      { name = "ATHENA_WORKGROUP",  value = var.athena_workgroup },
    ]

    secrets = [
      { name = "APIFY_API_TOKEN", valueFrom = var.apify_token_secret_arn },
      { name = "GEMINI_API_KEY",  valueFrom = var.gemini_api_key_secret_arn },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "pipeline"
      }
    }
  }])
}
