data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "web" {
  bucket        = "${var.app_name}-web-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "placeholder" {
  bucket       = aws_s3_bucket.web.id
  key          = "index.html"
  content_type = "text/html"
  content      = "<!doctype html><html><head><meta charset=\"utf-8\"><title>FB Marketplace Great Deals</title></head><body><h1>FB Marketplace Great Deals</h1><p>Coming soon.</p></body></html>"

  lifecycle {
    ignore_changes = [content, content_type, etag, source_hash]
  }
}
