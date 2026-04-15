resource "aws_athena_workgroup" "audit" {
  name        = "${var.project_name}-audit"
  description = "Workgroup para análisis de auditoría del trading bot"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_results.bucket}/results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}
