locals {
  firehose_common = {
    buffer_size     = var.firehose_buffer_size_mb
    buffer_interval = var.firehose_buffer_interval_seconds
    compression     = "SNAPPY"
  }
}

resource "aws_cloudwatch_log_group" "firehose_market_context" {
  name              = "/aws/firehose/${var.project_name}-market-context"
  retention_in_days = var.logs_retention_days
}

resource "aws_kinesis_firehose_delivery_stream" "market_context" {
  depends_on = [aws_cloudwatch_log_group.firehose_market_context]

  name        = "${var.project_name}-market-context"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose.arn
    bucket_arn = aws_s3_bucket.audit.arn

    prefix              = "market_context/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    error_output_prefix = "errors/market_context/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/!{firehose:error-output-type}/"

    buffering_size     = local.firehose_common.buffer_size
    buffering_interval = local.firehose_common.buffer_interval

    data_format_conversion_configuration {
      enabled = true
      input_format_configuration {
        deserializer {
          open_x_json_ser_de {}
        }
      }
      output_format_configuration {
        serializer {
          parquet_ser_de {
            compression = local.firehose_common.compression
          }
        }
      }
      schema_configuration {
        database_name = aws_glue_catalog_database.audit.name
        table_name    = aws_glue_catalog_table.market_context.name
        role_arn      = aws_iam_role.firehose.arn
      }
    }

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose_market_context.name
      log_stream_name = "S3Delivery"
    }
  }

  tags = {
    Project = var.project_name
    Table   = "market_context_log"
  }
}

resource "aws_kinesis_firehose_delivery_stream" "strategy_executions" {
  name        = "${var.project_name}-strategy-executions"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn            = aws_iam_role.firehose.arn
    bucket_arn          = aws_s3_bucket.audit.arn
    prefix              = "strategy_executions/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    error_output_prefix = "errors/strategy_executions/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/!{firehose:error-output-type}/"
    buffering_size      = local.firehose_common.buffer_size
    buffering_interval  = local.firehose_common.buffer_interval

    data_format_conversion_configuration {
      enabled = true
      input_format_configuration {
        deserializer {
          open_x_json_ser_de {}
        }
      }
      output_format_configuration {
        serializer {
          parquet_ser_de {
            compression = local.firehose_common.compression
          }
        }
      }
      schema_configuration {
        database_name = aws_glue_catalog_database.audit.name
        table_name    = aws_glue_catalog_table.strategy_executions.name
        role_arn      = aws_iam_role.firehose.arn
      }
    }
  }

  tags = { Project = var.project_name }
}

resource "aws_kinesis_firehose_delivery_stream" "opportunities" {
  name        = "${var.project_name}-opportunities"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn            = aws_iam_role.firehose.arn
    bucket_arn          = aws_s3_bucket.audit.arn
    prefix              = "opportunities/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    error_output_prefix = "errors/opportunities/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/!{firehose:error-output-type}/"
    buffering_size      = local.firehose_common.buffer_size
    buffering_interval  = local.firehose_common.buffer_interval

    data_format_conversion_configuration {
      enabled = true
      input_format_configuration {
        deserializer {
          open_x_json_ser_de {}
        }
      }
      output_format_configuration {
        serializer {
          parquet_ser_de {
            compression = local.firehose_common.compression
          }
        }
      }
      schema_configuration {
        database_name = aws_glue_catalog_database.audit.name
        table_name    = aws_glue_catalog_table.opportunities.name
        role_arn      = aws_iam_role.firehose.arn
      }
    }
  }

  tags = { Project = var.project_name }
}

resource "aws_kinesis_firehose_delivery_stream" "scan_cycles" {
  name        = "${var.project_name}-scan-cycles"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn            = aws_iam_role.firehose.arn
    bucket_arn          = aws_s3_bucket.audit.arn
    prefix              = "scan_cycles/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    error_output_prefix = "errors/scan_cycles/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/!{firehose:error-output-type}/"
    buffering_size      = local.firehose_common.buffer_size
    buffering_interval  = local.firehose_common.buffer_interval

    data_format_conversion_configuration {
      enabled = true
      input_format_configuration {
        deserializer {
          open_x_json_ser_de {}
        }
      }
      output_format_configuration {
        serializer {
          parquet_ser_de {
            compression = local.firehose_common.compression
          }
        }
      }
      schema_configuration {
        database_name = aws_glue_catalog_database.audit.name
        table_name    = aws_glue_catalog_table.scan_cycles.name
        role_arn      = aws_iam_role.firehose.arn
      }
    }
  }

  tags = { Project = var.project_name }
}

resource "aws_kinesis_firehose_delivery_stream" "trades" {
  name        = "${var.project_name}-trades"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn            = aws_iam_role.firehose.arn
    bucket_arn          = aws_s3_bucket.audit.arn
    prefix              = "trades/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    error_output_prefix = "errors/trades/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/!{firehose:error-output-type}/"
    buffering_size      = local.firehose_common.buffer_size
    buffering_interval  = local.firehose_common.buffer_interval

    data_format_conversion_configuration {
      enabled = true
      input_format_configuration {
        deserializer {
          open_x_json_ser_de {}
        }
      }
      output_format_configuration {
        serializer {
          parquet_ser_de {
            compression = local.firehose_common.compression
          }
        }
      }
      schema_configuration {
        database_name = aws_glue_catalog_database.audit.name
        table_name    = aws_glue_catalog_table.trades.name
        role_arn      = aws_iam_role.firehose.arn
      }
    }
  }

  tags = { Project = var.project_name }
}
