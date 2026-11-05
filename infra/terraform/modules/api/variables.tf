variable "app_name" {
  type = string
}

variable "package_dir" {
  description = "Folder produced by api/build_lambda.sh (source + Linux arm64 dependencies); zipped and deployed as the Lambda"
  type        = string
}

variable "subnet_ids" {
  description = "Subnets the Lambda runs in (private subnets; it only needs to reach Aurora inside the VPC)"
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group of the Lambda (Aurora's group allows it in)"
  type        = string
}

variable "db_host" {
  type = string
}

variable "db_port" {
  type = number
}

variable "db_name" {
  type = string
}

variable "db_reader_username" {
  description = "Read-only Postgres role (SELECT on the serving schema only)"
  type        = string
  default     = "web_serving_tables_reader"
}

variable "db_reader_password" {
  type      = string
  sensitive = true
}

variable "memory_size" {
  type    = number
  default = 512
}

variable "timeout" {
  description = "Seconds. Stays just under API Gateway's 30 s limit so the API can return its own error."
  type        = number
  default     = 28
}

variable "reserved_concurrency" {
  description = "Reserved concurrent executions for the API; -1 = unreserved. Needs a Lambda account quota above 10 (raise it first)."
  type        = number
  default     = -1
}

variable "throttle_rate_limit" {
  description = "API Gateway steady-state requests per second. Kept low: the account-wide Lambda limit is 10 and is shared with the fanout Lambda."
  type        = number
  default     = 2
}

variable "throttle_burst_limit" {
  type    = number
  default = 5
}
