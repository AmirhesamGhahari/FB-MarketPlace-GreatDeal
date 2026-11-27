# Phase 6.1 and 6.2: automatic deploys of the website API and the website.
#
#   API pipeline  : GitHub push that touches api/  ->  CodeBuild builds the Lambda package and updates the function.
#   Web pipeline  : GitHub push that touches web/, OR started by the Step Functions run right after dbt
#                   ->  CodeBuild builds the site and uploads it to S3, then clears the CloudFront cache.
#
# Both are CodePipeline V2 pipelines so that a push only starts the pipeline whose folder changed (path filters).
# The data-pipeline CodePipeline (modules/codepipeline, Docker image for ECS) is not touched.

data "aws_caller_identity" "current" {}

locals {
  distribution_arn = "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/${var.cloudfront_distribution_id}"
  logs_arn_prefix  = "arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group"
}

# ── IAM: the CodePipeline role (shared by both pipelines) ────────────────────

resource "aws_iam_role" "pipeline" {
  name = "${var.app_name}-deploy-pipelines"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codepipeline.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "pipeline" {
  name = "pipeline-permissions"
  role = aws_iam_role.pipeline.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject", "s3:GetObjectVersion", "s3:GetBucketVersioning",
          "s3:PutObjectAcl", "s3:PutObject"
        ]
        Resource = [var.artifact_bucket_arn, "${var.artifact_bucket_arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["codestar-connections:UseConnection"]
        Resource = var.connection_arn
      },
      {
        Effect   = "Allow"
        Action   = ["codebuild:BatchGetBuilds", "codebuild:StartBuild"]
        Resource = [aws_codebuild_project.api.arn, aws_codebuild_project.web.arn]
      }
    ]
  })
}

# ── CodeBuild: API deploy (6.1) ──────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/codebuild/${var.app_name}-api-deploy"
  retention_in_days = 14
}

resource "aws_iam_role" "api_build" {
  name = "${var.app_name}-api-deploy-codebuild"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codebuild.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "api_build" {
  name = "api-deploy-permissions"
  role = aws_iam_role.api_build.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${local.logs_arn_prefix}:${aws_cloudwatch_log_group.api.name}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject", "s3:GetObjectVersion", "s3:PutObject",
          "s3:GetBucketAcl", "s3:GetBucketLocation"
        ]
        Resource = [var.artifact_bucket_arn, "${var.artifact_bucket_arn}/*"]
      },
      {
        # `aws lambda wait function-updated` reads the configuration
        Effect   = "Allow"
        Action   = ["lambda:UpdateFunctionCode", "lambda:GetFunction", "lambda:GetFunctionConfiguration"]
        Resource = var.api_function_arn
      },
      {
        Effect   = "Allow"
        Action   = ["cloudfront:CreateInvalidation"]
        Resource = local.distribution_arn
      }
    ]
  })
}

resource "aws_codebuild_project" "api" {
  name         = "${var.app_name}-api-deploy"
  service_role = aws_iam_role.api_build.arn

  build_timeout = 30

  artifacts {
    type = "CODEPIPELINE"
  }

  # The Lambda dependencies are downloaded as prebuilt arm64 wheels (api/build_lambda.sh), so the build machine's own
  # CPU does not matter; x86 is the cheaper and more common image.
  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
    type         = "LINUX_CONTAINER"

    environment_variable {
      name  = "FUNCTION_NAME"
      value = var.api_function_name
    }
    environment_variable {
      name  = "CLOUDFRONT_DISTRIBUTION_ID"
      value = var.cloudfront_distribution_id
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = file("${path.module}/buildspec_api.yml")
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.api.name
    }
  }
}

# ── CodeBuild: website build and upload (6.2) ────────────────────────────────

resource "aws_cloudwatch_log_group" "web" {
  name              = "/aws/codebuild/${var.app_name}-web-build"
  retention_in_days = 14
}

resource "aws_iam_role" "web_build" {
  name = "${var.app_name}-web-build-codebuild"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codebuild.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "web_build" {
  name = "web-build-permissions"
  role = aws_iam_role.web_build.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${local.logs_arn_prefix}:${aws_cloudwatch_log_group.web.name}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject", "s3:GetObjectVersion", "s3:PutObject",
          "s3:GetBucketAcl", "s3:GetBucketLocation"
        ]
        Resource = [var.artifact_bucket_arn, "${var.artifact_bucket_arn}/*"]
      },
      {
        # `aws s3 sync --delete` lists the bucket, uploads new files and removes old ones
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = var.web_bucket_arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${var.web_bucket_arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
        Resource = local.distribution_arn
      }
    ]
  })
}

resource "aws_codebuild_project" "web" {
  name         = "${var.app_name}-web-build"
  service_role = aws_iam_role.web_build.arn

  # A cold build makes about 135 API calls at a polite pace (api.ts), plus Astro, Pagefind and the site checks.
  build_timeout = 30

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type = "BUILD_GENERAL1_MEDIUM"
    image        = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
    type         = "LINUX_CONTAINER"

    environment_variable {
      name  = "WEB_BUCKET"
      value = var.web_bucket_name
    }
    environment_variable {
      name  = "CLOUDFRONT_DISTRIBUTION_ID"
      value = var.cloudfront_distribution_id
    }
    # The launch switch (see web/src/lib/site.ts): anything but "true" builds the hidden version.
    environment_variable {
      name  = "PUBLIC_SITE_LIVE"
      value = var.site_live ? "true" : "false"
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = file("${path.module}/buildspec_web.yml")
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.web.name
    }
  }
}

# ── The two pipelines ────────────────────────────────────────────────────────

resource "aws_codepipeline" "api" {
  name          = "${var.app_name}-api-pipeline"
  role_arn      = aws_iam_role.pipeline.arn
  pipeline_type = "V2"
  # One run after the other, never dropped: two quick pushes both get deployed, in order.
  execution_mode = "QUEUED"

  artifact_store {
    location = var.artifact_bucket_name
    type     = "S3"
  }

  stage {
    name = "Source"
    action {
      name             = "GitHub"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["source"]

      configuration = {
        ConnectionArn    = var.connection_arn
        FullRepositoryId = "${var.github_owner}/${var.github_repo}"
        BranchName       = var.github_branch
      }
    }
  }

  stage {
    name = "DeployApi"
    action {
      name            = "BuildAndUpdateLambda"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["source"]

      configuration = {
        ProjectName = aws_codebuild_project.api.name
      }
    }
  }

  # Only a push that changes something under api/ starts this pipeline.
  trigger {
    provider_type = "CodeStarSourceConnection"
    git_configuration {
      source_action_name = "GitHub"
      push {
        branches {
          includes = [var.github_branch]
        }
        file_paths {
          includes = ["api/**"]
        }
      }
    }
  }
}

resource "aws_codepipeline" "web" {
  name           = "${var.app_name}-web-pipeline"
  role_arn       = aws_iam_role.pipeline.arn
  pipeline_type  = "V2"
  execution_mode = "QUEUED"

  artifact_store {
    location = var.artifact_bucket_name
    type     = "S3"
  }

  stage {
    name = "Source"
    action {
      name             = "GitHub"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["source"]

      configuration = {
        ConnectionArn    = var.connection_arn
        FullRepositoryId = "${var.github_owner}/${var.github_repo}"
        BranchName       = var.github_branch
      }
    }
  }

  stage {
    name = "BuildWeb"
    action {
      name            = "BuildAndUploadSite"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["source"]

      configuration = {
        ProjectName = aws_codebuild_project.web.name
      }
    }
  }

  # A push that changes web/ starts it. The Step Functions run also starts it after every dbt run
  # (a manual start is always allowed, whatever the filters say).
  trigger {
    provider_type = "CodeStarSourceConnection"
    git_configuration {
      source_action_name = "GitHub"
      push {
        branches {
          includes = [var.github_branch]
        }
        file_paths {
          includes = ["web/**"]
        }
      }
    }
  }
}
