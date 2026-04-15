locals {
  audit_bucket = var.audit_bucket_name != "" ? var.audit_bucket_name : "${var.project_name}-audit-${data.aws_caller_identity.current.account_id}"
  athena_results_bucket = var.athena_results_bucket != "" ? var.athena_results_bucket : "${var.project_name}-athena-results-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "audit" {
  bucket = local.audit_bucket

  tags = {
    Project     = var.project_name
    Environment = var.environment
    Purpose     = "audit-analytics"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    id     = "archive-to-glacier"
    status = "Enabled"
    filter { prefix = "" }
    transition {
      days          = var.s3_glacier_transition_days
      storage_class = "GLACIER"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "audit" {
  bucket                  = aws_s3_bucket.audit.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "athena_results" {
  bucket = local.athena_results_bucket

  tags = {
    Project = var.project_name
    Purpose   = "athena-query-results"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  rule {
    id     = "delete-old-results"
    status = "Enabled"
    filter { prefix = "" }
    expiration {
      days = 30
    }
  }
}

resource "aws_s3_bucket_public_access_block" "athena_results" {
  bucket                  = aws_s3_bucket.athena_results.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
