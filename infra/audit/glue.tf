locals {
  glue_partition_params = {
    "projection.enabled"      = "true"
    "projection.year.type"    = "integer"
    "projection.year.range"   = "2026,2030"
    "projection.month.type"   = "integer"
    "projection.month.range"  = "1,12"
    "projection.month.digits" = "2"
    "projection.day.type"     = "integer"
    "projection.day.range"    = "1,31"
    "projection.day.digits"   = "2"
  }

  market_context_cols = [
    ["scan_id", "string"], ["timestamp", "string"], ["pair", "string"], ["tier", "string"],
    ["trend", "string"], ["volatility", "string"], ["volume_state", "string"],
    ["atr_viable", "boolean"], ["bb_squeeze", "boolean"], ["tradeable", "boolean"],
    ["ema21", "double"], ["ema50", "double"], ["close", "double"],
    ["atr_current", "double"], ["atr_avg", "double"], ["atr_ratio", "double"],
    ["vol_actual", "double"], ["vol_avg", "double"], ["vol_ratio", "double"],
    ["bb_width", "double"], ["bb_width_avg", "double"], ["session", "string"], ["event_type", "string"],
  ]

  strategy_executions_cols = [
    ["scan_id", "string"], ["timestamp", "string"], ["pair", "string"], ["strategy", "string"],
    ["resultado", "string"], ["condicion_falla", "string"], ["valor_condicion", "string"],
    ["entry_price", "double"], ["sl_price", "double"], ["sl_pct", "double"],
    ["tp1_price", "double"], ["tp2_price", "double"], ["rr_ratio", "double"],
    ["session", "string"], ["event_type", "string"],
  ]

  opportunities_cols = [
    ["opportunity_id", "string"], ["scan_id", "string"], ["timestamp", "string"],
    ["pair", "string"], ["tier", "string"], ["strategy", "string"], ["timeframe", "string"],
    ["entry_price", "double"], ["sl_price", "double"], ["sl_pct", "double"], ["sl_type", "string"],
    ["tp1_price", "double"], ["tp2_price", "double"], ["rr_ratio", "double"],
    ["risk_usd", "double"], ["position_size_usd", "double"], ["confluence", "boolean"],
    ["drift_pct", "double"], ["session", "string"], ["event_type", "string"],
  ]

  scan_cycles_cols = [
    ["scan_id", "string"], ["timestamp", "string"], ["pares_evaluados", "int"], ["pares_operables", "int"],
    ["descartados_trend", "int"], ["descartados_volume", "int"], ["descartados_volatility", "int"],
    ["descartados_atr", "int"], ["descartados_squeeze", "int"], ["oportunidades_brutas", "int"],
    ["descartadas_rr", "int"], ["descartadas_sl_pct", "int"], ["descartadas_cooldown", "int"],
    ["enviadas_telegram", "int"], ["duracion_ms", "int"], ["errores", "int"],
    ["session", "string"], ["event_type", "string"],
  ]

  trades_cols = [
    ["trade_id", "string"], ["opportunity_id", "string"], ["mode", "string"], ["pair", "string"],
    ["tier", "string"], ["strategy", "string"], ["timeframe", "string"],
    ["entry_price", "double"], ["exit_price", "double"], ["sl_initial", "double"], ["sl_final", "double"],
    ["sl_type", "string"], ["sl_pct", "double"], ["tp1_price", "double"], ["tp2_price", "double"],
    ["tp1_hit", "boolean"], ["trailing_activated", "boolean"], ["close_reason", "string"],
    ["gross_pnl", "double"], ["net_pnl", "double"], ["commission", "double"],
    ["r_multiple", "double"], ["rr_planned", "double"], ["rr_actual", "double"],
    ["mfe", "double"], ["mae", "double"], ["duration_minutes", "int"],
    ["market_trend", "string"], ["market_volatility", "string"], ["session", "string"],
    ["confluence", "boolean"], ["capital_at_open", "double"], ["risk_pct", "double"],
    ["risk_usd", "double"], ["position_size_usd", "double"], ["started_at", "string"],
    ["ended_at", "string"], ["event_type", "string"],
  ]

  glue_prefixes = ["market_context", "strategy_executions", "opportunities", "scan_cycles", "trades"]
}

resource "aws_glue_catalog_database" "audit" {
  name        = var.glue_database_name
  description = "Auditoría analítica del trading bot"
}

resource "aws_glue_catalog_table" "market_context" {
  name          = "market_context_log"
  database_name = aws_glue_catalog_database.audit.name
  table_type    = "EXTERNAL_TABLE"

  parameters = merge(
    {
      "classification"      = "parquet"
      "parquet.compression" = "SNAPPY"
      "storage.location.template" = "s3://${aws_s3_bucket.audit.bucket}/market_context/year=$${year}/month=$${month}/day=$${day}/"
    },
    local.glue_partition_params
  )

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.audit.bucket}/market_context/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters            = { "serialization.format" = "1" }
    }

    dynamic "columns" {
      for_each = local.market_context_cols
      content {
        name = columns.value[0]
        type = columns.value[1]
      }
    }
  }

  partition_keys {
    name = "year"
    type = "int"
  }
  partition_keys {
    name = "month"
    type = "int"
  }
  partition_keys {
    name = "day"
    type = "int"
  }
}

resource "aws_glue_catalog_table" "strategy_executions" {
  name          = "strategy_executions"
  database_name = aws_glue_catalog_database.audit.name
  table_type    = "EXTERNAL_TABLE"

  parameters = merge(
    {
      "classification"            = "parquet"
      "parquet.compression"       = "SNAPPY"
      "storage.location.template" = "s3://${aws_s3_bucket.audit.bucket}/strategy_executions/year=$${year}/month=$${month}/day=$${day}/"
    },
    local.glue_partition_params
  )

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.audit.bucket}/strategy_executions/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters            = { "serialization.format" = "1" }
    }

    dynamic "columns" {
      for_each = local.strategy_executions_cols
      content {
        name = columns.value[0]
        type = columns.value[1]
      }
    }
  }

  partition_keys {
    name = "year"
    type = "int"
  }
  partition_keys {
    name = "month"
    type = "int"
  }
  partition_keys {
    name = "day"
    type = "int"
  }
}

resource "aws_glue_catalog_table" "opportunities" {
  name          = "opportunities"
  database_name = aws_glue_catalog_database.audit.name
  table_type    = "EXTERNAL_TABLE"

  parameters = merge(
    {
      "classification"            = "parquet"
      "parquet.compression"       = "SNAPPY"
      "storage.location.template" = "s3://${aws_s3_bucket.audit.bucket}/opportunities/year=$${year}/month=$${month}/day=$${day}/"
    },
    local.glue_partition_params
  )

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.audit.bucket}/opportunities/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters            = { "serialization.format" = "1" }
    }

    dynamic "columns" {
      for_each = local.opportunities_cols
      content {
        name = columns.value[0]
        type = columns.value[1]
      }
    }
  }

  partition_keys {
    name = "year"
    type = "int"
  }
  partition_keys {
    name = "month"
    type = "int"
  }
  partition_keys {
    name = "day"
    type = "int"
  }
}

resource "aws_glue_catalog_table" "scan_cycles" {
  name          = "scan_cycles"
  database_name = aws_glue_catalog_database.audit.name
  table_type    = "EXTERNAL_TABLE"

  parameters = merge(
    {
      "classification"            = "parquet"
      "parquet.compression"       = "SNAPPY"
      "storage.location.template" = "s3://${aws_s3_bucket.audit.bucket}/scan_cycles/year=$${year}/month=$${month}/day=$${day}/"
    },
    local.glue_partition_params
  )

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.audit.bucket}/scan_cycles/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters            = { "serialization.format" = "1" }
    }

    dynamic "columns" {
      for_each = local.scan_cycles_cols
      content {
        name = columns.value[0]
        type = columns.value[1]
      }
    }
  }

  partition_keys {
    name = "year"
    type = "int"
  }
  partition_keys {
    name = "month"
    type = "int"
  }
  partition_keys {
    name = "day"
    type = "int"
  }
}

resource "aws_glue_catalog_table" "trades" {
  name          = "trades"
  database_name = aws_glue_catalog_database.audit.name
  table_type    = "EXTERNAL_TABLE"

  parameters = merge(
    {
      "classification"            = "parquet"
      "parquet.compression"       = "SNAPPY"
      "storage.location.template" = "s3://${aws_s3_bucket.audit.bucket}/trades/year=$${year}/month=$${month}/day=$${day}/"
    },
    local.glue_partition_params
  )

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.audit.bucket}/trades/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters            = { "serialization.format" = "1" }
    }

    dynamic "columns" {
      for_each = local.trades_cols
      content {
        name = columns.value[0]
        type = columns.value[1]
      }
    }
  }

  partition_keys {
    name = "year"
    type = "int"
  }
  partition_keys {
    name = "month"
    type = "int"
  }
  partition_keys {
    name = "day"
    type = "int"
  }
}

resource "aws_glue_crawler" "audit" {
  name          = "${var.project_name}-audit-crawler"
  role          = aws_iam_role.glue_crawler.arn
  database_name = aws_glue_catalog_database.audit.name
  description   = "Detecta nuevas particiones y cambios de schema en el bucket de auditoría"

  schedule = var.crawler_schedule

  dynamic "s3_target" {
    for_each = local.glue_prefixes
    content {
      path = "s3://${aws_s3_bucket.audit.bucket}/${s3_target.value}/"
    }
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  configuration = jsonencode({
    Version = 1.0
    CrawlerOutput = {
      Partitions = { AddOrUpdateBehavior = "InheritFromTable" }
    }
  })
}
