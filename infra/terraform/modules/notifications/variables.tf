variable "app_name" {
  type = string
}

variable "alert_email" {
  description = "Email address subscribed to the deal alerts topic. AWS sends a confirmation email that must be clicked after apply."
  type        = string
}
