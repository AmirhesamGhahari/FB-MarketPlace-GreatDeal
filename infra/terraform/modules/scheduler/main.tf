data "archive_file" "fanout" {
  type        = "zip"
  source_dir  = var.lambda_source_dir
  output_path = "${path.module}/fanout.zip"
}

# ── DynamoDB: per-config run state (pk = "{config}#facebook_legacy") ──────────
resource "aws_dynamodb_table" "pipeline_state" {
  name         = "${var.app_name}-pipeline-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  tags = { App = var.app_name }
}

# ── Lambda: TaskProducer — reads DynamoDB mode, returns task list for SFN ─────
resource "aws_iam_role" "lambda" {
  name = "${var.app_name}-fanout-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "dispatcher-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:BatchGetItem"]
      Resource = [aws_dynamodb_table.pipeline_state.arn]
    }]
  })
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.app_name}-fanout"
  retention_in_days = 14
}

resource "aws_lambda_function" "fanout" {
  function_name    = "${var.app_name}-fanout"
  filename         = data.archive_file.fanout.output_path
  source_code_hash = data.archive_file.fanout.output_base64sha256
  role             = aws_iam_role.lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 60

  depends_on = [aws_cloudwatch_log_group.lambda]

  environment {
    variables = {
      STATE_TABLE_NAME = aws_dynamodb_table.pipeline_state.name
      CATEGORY_CONFIGS = jsonencode(var.category_configs)
    }
  }
}

# ── Step Functions ─────────────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/states/${var.app_name}-dispatcher"
  retention_in_days = 30
}

resource "aws_iam_role" "sfn" {
  name = "${var.app_name}-sfn-dispatcher"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "sfn_policy" {
  name = "sfn-dispatcher-policy"
  role = aws_iam_role.sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask", "ecs:StopTask", "ecs:DescribeTasks"]
        Resource = ["arn:aws:ecs:*:*:task-definition/${var.task_family}:*", "arn:aws:ecs:*:*:task/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [var.execution_role_arn, var.task_role_arn]
      },
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [aws_lambda_function.fanout.arn]
      },
      {
        # .sync integration — SFN creates/manages this EventBridge rule internally
        Effect   = "Allow"
        Action   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
        Resource = ["arn:aws:events:*:*:rule/StepFunctionsGetEventsForECSTaskRule"]
      },
      {
        # Marks mode=periodic after each successful ECS task
        Effect   = "Allow"
        Action   = ["dynamodb:UpdateItem"]
        Resource = [aws_dynamodb_table.pipeline_state.arn]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery", "logs:ListLogDeliveries",
          "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"
        ]
        Resource = ["*"]
      }
    ]
  })
}

# ── Locals: ASL building blocks ───────────────────────────────────────────────
locals {
  lambda_retry = [{
    ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"]
    IntervalSeconds = 2
    MaxAttempts     = 3
    BackoffRate     = 2
  }]

  _ecs_task_params = {
    LaunchType     = "FARGATE"
    Cluster        = var.ecs_cluster_arn
    TaskDefinition = var.task_family
    NetworkConfiguration = {
      AwsvpcConfiguration = {
        Subnets        = var.public_subnet_ids
        SecurityGroups = [var.ecs_task_sg_id]
        AssignPublicIp = "ENABLED"
      }
    }
    Overrides = {
      ContainerOverrides = [{
        Name        = "pipeline"
        "Command.$" = "$.task.command"
      }]
    }
  }

  _dynamo_set_periodic_params = {
    TableName = aws_dynamodb_table.pipeline_state.name
    Key = {
      pk = { "S.$" = "$.task.state_key" }
    }
    UpdateExpression          = "SET #m = :periodic"
    ExpressionAttributeNames  = { "#m" = "mode" }
    ExpressionAttributeValues = { ":periodic" = { "S" = "periodic" } }
  }

  task_iterator_fl = {
    StartAt = "LaunchFL"
    States = {
      LaunchFL = {
        Type           = "Task"
        Resource       = "arn:aws:states:::ecs:runTask.sync"
        TimeoutSeconds = 18000
        Parameters     = local._ecs_task_params
        ResultPath     = null
        Next           = "SetPeriodicFL"
        Catch          = [{ ErrorEquals = ["States.ALL"], ResultPath = null, Next = "EndFL" }]
      }
      SetPeriodicFL = {
        Type       = "Task"
        Resource   = "arn:aws:states:::dynamodb:updateItem"
        Parameters = local._dynamo_set_periodic_params
        ResultPath = null
        Next       = "EndFL"
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = null, Next = "EndFL" }]
      }
      EndFL = { Type = "Pass", End = true }
    }
  }
}

# ── State machine ──────────────────────────────────────────────────────────────
#
# Flow: EventBridge → SFN
#   TaskProducer (Lambda) — reads DynamoDB mode per config, returns task list
#   RunFBLegacy (Map, MaxConcurrency=1) — for each config:
#     LaunchFL       — ECS runTask.sync: Fargate runs pipeline, SFN waits via EventBridge
#     SetPeriodicFL  — DynamoDB UpdateItem: marks mode=periodic after first success
#     EndFL          — terminal Pass
#
resource "aws_sfn_state_machine" "dispatcher" {
  name     = "${var.app_name}-dispatcher"
  role_arn = aws_iam_role.sfn.arn

  logging_configuration {
    level                  = "ERROR"
    include_execution_data = true
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
  }

  definition = jsonencode({
    Comment = "FB Marketplace Great Deals — pipeline dispatcher"
    StartAt = "TaskProducer"

    States = {
      TaskProducer = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.fanout.arn
          "Payload.$"  = "$"
        }
        ResultSelector = {
          "run.$"   = "$.Payload.run"
          "tasks.$" = "$.Payload.tasks"
        }
        Retry = local.lambda_retry
        Next  = "RunFBLegacy"
      }

      RunFBLegacy = {
        Type           = "Map"
        ItemsPath      = "$.tasks.facebook_legacy"
        MaxConcurrency = 1
        Parameters     = { "task.$" = "$$.Map.Item.Value" }
        Iterator       = local.task_iterator_fl
        End            = true
      }
    }
  })

  depends_on = [aws_cloudwatch_log_group.sfn]
}

# ── EventBridge Scheduler → Step Functions ─────────────────────────────────────
# Fires at 00:00 UTC and 12:00 UTC (twice daily).
resource "aws_iam_role" "scheduler" {
  name = "${var.app_name}-eventbridge-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name = "start-step-functions"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["states:StartExecution"]
      Resource = [aws_sfn_state_machine.dispatcher.arn]
    }]
  })
}

resource "aws_scheduler_schedule" "dispatcher" {
  name       = "${var.app_name}-dispatcher"
  group_name = "default"

  flexible_time_window { mode = "OFF" }

  schedule_expression          = "cron(0 */12 * * ? *)"
  schedule_expression_timezone = "UTC"

  target {
    arn      = aws_sfn_state_machine.dispatcher.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = "{}"
  }
}
