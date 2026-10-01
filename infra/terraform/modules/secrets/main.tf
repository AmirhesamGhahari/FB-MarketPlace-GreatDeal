resource "aws_secretsmanager_secret" "db_url" {
  name                    = "${var.app_name}/database-url"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "db_url" {
  secret_id = aws_secretsmanager_secret.db_url.id
  secret_string = join("", [
    "postgresql://",
    var.db_master_username, ":", var.db_master_password,
    "@", var.aurora_endpoint, ":", tostring(var.aurora_port),
    "/", var.db_name
  ])
}

