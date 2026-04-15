# CURSOR PROMPT — Infraestructura de Auditoría: Firehose + S3 + Glue + Athena (Terraform)

---

## Contexto del proyecto

Bot de trading en AWS Lambda que necesita auditoría analítica completa.
Los Lambdas ya existen (ScannerFunction, WebhookFunction, PositionMonitorFunction,
BinanceEventsFunction, KeepAliveFunction) y emiten logs JSON estructurados a CloudWatch.

Hay que construir el pipeline completo:
```
Lambda → CloudWatch Logs → Subscription Filter → Kinesis Firehose
→ S3 (Parquet, particionado por año/mes/día) → Glue Crawler → Athena
```

Todo en **Terraform**. Sin SAM, sin CDK, solo Terraform puro.

---

## Estructura de archivos requerida

```
infra/
├── main.tf                    # provider, backend, locals
├── variables.tf               # todas las variables
├── outputs.tf                 # outputs útiles (bucket, Athena DB, etc.)
├── audit/
│   ├── s3.tf                  # bucket S3 + lifecycle + encryption
│   ├── firehose.tf            # 4 delivery streams (uno por tabla)
│   ├── glue.tf                # database + crawler + schemas de tablas
│   ├── athena.tf              # workgroup + query results bucket
│   ├── cloudwatch.tf          # subscription filters CloudWatch → Firehose
│   ├── iam.tf                 # roles y políticas para Firehose, Glue, Athena
│   └── saved_queries.tf       # queries guardadas en Athena
├── lambdas/
│   └── (existente — no modificar)
└── README_AUDIT.md            # instrucciones de uso
```

---

## Variables requeridas (`variables.tf`)

```hcl
variable "aws_region" {
  description = "Región AWS del proyecto"
  default     = "ap-northeast-1"
}

variable "environment" {
  description = "Ambiente: dev, staging, prod"
  default     = "prod"
}

variable "project_name" {
  description = "Prefijo para todos los recursos"
  default     = "trading-bot"
}

variable "audit_bucket_name" {
  description = "Nombre del bucket S3 de auditoría"
  default     = "trading-bot-audit"
}

variable "glue_database_name" {
  description = "Nombre de la base de datos en Glue"
  default     = "trading_bot_audit"
}

variable "athena_results_bucket" {
  description = "Bucket para resultados de queries de Athena"
  default     = "trading-bot-athena-results"
}

variable "firehose_buffer_size_mb" {
  description = "MB antes de hacer flush a S3"
  default     = 5
}

variable "firehose_buffer_interval_seconds" {
  description = "Segundos máximos antes de hacer flush"
  default     = 60
}

variable "logs_retention_days" {
  description = "Días de retención en CloudWatch antes de pasar a S3"
  default     = 7
}

variable "s3_glacier_transition_days" {
  description = "Días hasta mover a Glacier"
  default     = 90
}

variable "crawler_schedule" {
  description = "Cron para el Glue Crawler (UTC)"
  default     = "cron(30 0 * * ? *)"  # 00:30 UTC todos los días
}

# ARNs de los log groups existentes de los Lambdas
variable "scanner_log_group_name" {
  default = "/aws/lambda/trading-bot-scanner"
}

variable "monitor_log_group_name" {
  default = "/aws/lambda/trading-bot-position-monitor"
}

variable "binance_events_log_group_name" {
  default = "/aws/lambda/trading-bot-binance-events"
}
```

---

## S3 (`audit/s3.tf`)

Crear **dos buckets**:
1. `audit_bucket` — datos de auditoría en Parquet
2. `athena_results_bucket` — resultados temporales de queries Athena

```hcl
# Bucket principal de auditoría
resource "aws_s3_bucket" "audit" {
  bucket = var.audit_bucket_name

  tags = {
    Project     = var.project_name
    Environment = var.environment
    Purpose     = "audit-analytics"
  }
}

resource "aws_s3_bucket_versioning" "audit" {
  bucket = aws_s3_bucket.audit.id
  versioning_configuration {
    status = "Disabled"  # no necesitamos versioning para logs
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

    transition {
      days          = var.s3_glacier_transition_days
      storage_class = "GLACIER"
    }

    # Prefijos de cada tabla
    filter {
      prefix = ""  # aplica a todo el bucket
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

# Bucket para resultados de Athena
resource "aws_s3_bucket" "athena_results" {
  bucket = var.athena_results_bucket
}

resource "aws_s3_bucket_lifecycle_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  rule {
    id     = "delete-old-results"
    status = "Enabled"

    expiration {
      days = 30  # resultados de queries se borran a los 30 días
    }

    filter {
      prefix = ""
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
```

---

## IAM (`audit/iam.tf`)

Crear roles para: Firehose, Glue Crawler, Athena, CloudWatch Subscription.

```hcl
# ── FIREHOSE ROLE ──────────────────────────────────────────────────────────

resource "aws_iam_role" "firehose" {
  name = "${var.project_name}-firehose-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "firehose.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "firehose" {
  name = "${var.project_name}-firehose-policy"
  role = aws_iam_role.firehose.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:AbortMultipartUpload",
          "s3:GetBucketLocation",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:ListBucketMultipartUploads",
          "s3:PutObject"
        ]
        Resource = [
          aws_s3_bucket.audit.arn,
          "${aws_s3_bucket.audit.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "glue:GetTable",
          "glue:GetTableVersion",
          "glue:GetTableVersions"
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:PutLogEvents"]
        Resource = "*"
      }
    ]
  })
}

# ── CLOUDWATCH SUBSCRIPTION ROLE ──────────────────────────────────────────

resource "aws_iam_role" "cloudwatch_subscription" {
  name = "${var.project_name}-cw-subscription-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = {
        Service = "logs.${var.aws_region}.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "cloudwatch_subscription" {
  name = "${var.project_name}-cw-subscription-policy"
  role = aws_iam_role.cloudwatch_subscription.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "firehose:PutRecord",
        "firehose:PutRecordBatch"
      ]
      Resource = [
        aws_kinesis_firehose_delivery_stream.market_context.arn,
        aws_kinesis_firehose_delivery_stream.strategy_executions.arn,
        aws_kinesis_firehose_delivery_stream.opportunities.arn,
        aws_kinesis_firehose_delivery_stream.scan_cycles.arn,
        aws_kinesis_firehose_delivery_stream.trades.arn,
      ]
    }]
  })
}

# ── GLUE CRAWLER ROLE ─────────────────────────────────────────────────────

resource "aws_iam_role" "glue_crawler" {
  name = "${var.project_name}-glue-crawler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_crawler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3" {
  name = "${var.project_name}-glue-s3-policy"
  role = aws_iam_role.glue_crawler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.audit.arn,
        "${aws_s3_bucket.audit.arn}/*"
      ]
    }]
  })
}

# ── ATHENA ROLE ───────────────────────────────────────────────────────────

resource "aws_iam_role" "athena" {
  name = "${var.project_name}-athena-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "athena.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "athena" {
  name = "${var.project_name}-athena-policy"
  role = aws_iam_role.athena.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.audit.arn,
          "${aws_s3_bucket.audit.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.athena_results.arn,
          "${aws_s3_bucket.athena_results.arn}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["glue:*"]
        Resource = "*"
      }
    ]
  })
}
```

---

## Firehose (`audit/firehose.tf`)

Crear **5 delivery streams**, uno por tabla.
Cada uno lee de CloudWatch y escribe Parquet en S3 particionado por `año/mes/día`.

```hcl
# ── LOCAL para reutilizar configuración común ──────────────────────────────

locals {
  firehose_common = {
    buffer_size     = var.firehose_buffer_size_mb
    buffer_interval = var.firehose_buffer_interval_seconds
    compression     = "SNAPPY"
  }
}

# ── HELPER: módulo local para crear streams ────────────────────────────────
# Repetir este bloque para cada tabla cambiando name, prefix y table_name

# 1. market_context_log
resource "aws_kinesis_firehose_delivery_stream" "market_context" {
  name        = "${var.project_name}-market-context"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose.arn
    bucket_arn = aws_s3_bucket.audit.arn

    # Particionado por año/mes/día
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
      log_group_name  = "/aws/firehose/${var.project_name}-market-context"
      log_stream_name = "S3Delivery"
    }
  }

  tags = {
    Project = var.project_name
    Table   = "market_context_log"
  }
}

# 2. strategy_executions
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
        deserializer { open_x_json_ser_de {} }
      }
      output_format_configuration {
        serializer {
          parquet_ser_de { compression = local.firehose_common.compression }
        }
      }
      schema_configuration {
        database_name = aws_glue_catalog_database.audit.name
        table_name    = aws_glue_catalog_table.strategy_executions.name
        role_arn      = aws_iam_role.firehose.arn
      }
    }
  }
}

# 3. opportunities
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
        deserializer { open_x_json_ser_de {} }
      }
      output_format_configuration {
        serializer {
          parquet_ser_de { compression = local.firehose_common.compression }
        }
      }
      schema_configuration {
        database_name = aws_glue_catalog_database.audit.name
        table_name    = aws_glue_catalog_table.opportunities.name
        role_arn      = aws_iam_role.firehose.arn
      }
    }
  }
}

# 4. scan_cycles
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
        deserializer { open_x_json_ser_de {} }
      }
      output_format_configuration {
        serializer {
          parquet_ser_de { compression = local.firehose_common.compression }
        }
      }
      schema_configuration {
        database_name = aws_glue_catalog_database.audit.name
        table_name    = aws_glue_catalog_table.scan_cycles.name
        role_arn      = aws_iam_role.firehose.arn
      }
    }
  }
}

# 5. trades
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
        deserializer { open_x_json_ser_de {} }
      }
      output_format_configuration {
        serializer {
          parquet_ser_de { compression = local.firehose_common.compression }
        }
      }
      schema_configuration {
        database_name = aws_glue_catalog_database.audit.name
        table_name    = aws_glue_catalog_table.trades.name
        role_arn      = aws_iam_role.firehose.arn
      }
    }
  }
}
```

---

## Glue (`audit/glue.tf`)

Database + 5 tablas con schema explícito + Crawler.

```hcl
resource "aws_glue_catalog_database" "audit" {
  name        = var.glue_database_name
  description = "Auditoría analítica del trading bot"
}

# ── TABLA 1: market_context_log ────────────────────────────────────────────

resource "aws_glue_catalog_table" "market_context" {
  name          = "market_context_log"
  database_name = aws_glue_catalog_database.audit.name

  table_type = "EXTERNAL_TABLE"

  parameters = {
    "classification"       = "parquet"
    "parquet.compression"  = "SNAPPY"
    "projection.enabled"   = "true"

    # Proyección de particiones — evita depender del crawler para consultar
    "projection.year.type"          = "integer"
    "projection.year.range"         = "2026,2030"
    "projection.month.type"         = "integer"
    "projection.month.range"        = "1,12"
    "projection.month.digits"       = "2"
    "projection.day.type"           = "integer"
    "projection.day.range"          = "1,31"
    "projection.day.digits"         = "2"
    "storage.location.template"     = "s3://${var.audit_bucket_name}/market_context/year=$${year}/month=$${month}/day=$${day}/"
  }

  storage_descriptor {
    location      = "s3://${var.audit_bucket_name}/market_context/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters = { "serialization.format" = "1" }
    }

    columns {
      name = "scan_id"       type = "string"
      name = "timestamp"     type = "string"
      name = "pair"          type = "string"
      name = "tier"          type = "string"
      name = "trend"         type = "string"
      name = "volatility"    type = "string"
      name = "volume_state"  type = "string"
      name = "atr_viable"    type = "boolean"
      name = "bb_squeeze"    type = "boolean"
      name = "tradeable"     type = "boolean"
      name = "ema21"         type = "double"
      name = "ema50"         type = "double"
      name = "close"         type = "double"
      name = "atr_current"   type = "double"
      name = "atr_avg"       type = "double"
      name = "atr_ratio"     type = "double"
      name = "vol_actual"    type = "double"
      name = "vol_avg"       type = "double"
      name = "vol_ratio"     type = "double"
      name = "bb_width"      type = "double"
      name = "bb_width_avg"  type = "double"
      name = "session"       type = "string"
      name = "event_type"    type = "string"
    }
  }

  partition_keys {
    name = "year"  type = "int"
    name = "month" type = "int"
    name = "day"   type = "int"
  }
}

# ── TABLA 2: strategy_executions ───────────────────────────────────────────

resource "aws_glue_catalog_table" "strategy_executions" {
  name          = "strategy_executions"
  database_name = aws_glue_catalog_database.audit.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"      = "parquet"
    "parquet.compression" = "SNAPPY"
    "projection.enabled"  = "true"
    "projection.year.type"      = "integer"
    "projection.year.range"     = "2026,2030"
    "projection.month.type"     = "integer"
    "projection.month.range"    = "1,12"
    "projection.month.digits"   = "2"
    "projection.day.type"       = "integer"
    "projection.day.range"      = "1,31"
    "projection.day.digits"     = "2"
    "storage.location.template" = "s3://${var.audit_bucket_name}/strategy_executions/year=$${year}/month=$${month}/day=$${day}/"
  }

  storage_descriptor {
    location      = "s3://${var.audit_bucket_name}/strategy_executions/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters = { "serialization.format" = "1" }
    }

    columns {
      name = "scan_id"          type = "string"
      name = "timestamp"        type = "string"
      name = "pair"             type = "string"
      name = "strategy"         type = "string"
      name = "resultado"        type = "string"
      name = "condicion_falla"  type = "string"
      name = "valor_condicion"  type = "string"
      name = "entry_price"      type = "double"
      name = "sl_price"         type = "double"
      name = "sl_pct"           type = "double"
      name = "tp1_price"        type = "double"
      name = "tp2_price"        type = "double"
      name = "rr_ratio"         type = "double"
      name = "session"          type = "string"
      name = "event_type"       type = "string"
    }
  }

  partition_keys {
    name = "year"  type = "int"
    name = "month" type = "int"
    name = "day"   type = "int"
  }
}

# ── TABLA 3: opportunities ─────────────────────────────────────────────────

resource "aws_glue_catalog_table" "opportunities" {
  name          = "opportunities"
  database_name = aws_glue_catalog_database.audit.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"      = "parquet"
    "parquet.compression" = "SNAPPY"
    "projection.enabled"  = "true"
    "projection.year.type"      = "integer"
    "projection.year.range"     = "2026,2030"
    "projection.month.type"     = "integer"
    "projection.month.range"    = "1,12"
    "projection.month.digits"   = "2"
    "projection.day.type"       = "integer"
    "projection.day.range"      = "1,31"
    "projection.day.digits"     = "2"
    "storage.location.template" = "s3://${var.audit_bucket_name}/opportunities/year=$${year}/month=$${month}/day=$${day}/"
  }

  storage_descriptor {
    location      = "s3://${var.audit_bucket_name}/opportunities/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters = { "serialization.format" = "1" }
    }

    columns {
      name = "opportunity_id"    type = "string"
      name = "scan_id"           type = "string"
      name = "timestamp"         type = "string"
      name = "pair"              type = "string"
      name = "tier"              type = "string"
      name = "strategy"          type = "string"
      name = "timeframe"         type = "string"
      name = "entry_price"       type = "double"
      name = "sl_price"          type = "double"
      name = "sl_pct"            type = "double"
      name = "sl_type"           type = "string"
      name = "tp1_price"         type = "double"
      name = "tp2_price"         type = "double"
      name = "rr_ratio"          type = "double"
      name = "risk_usd"          type = "double"
      name = "position_size_usd" type = "double"
      name = "confluence"        type = "boolean"
      name = "drift_pct"         type = "double"
      name = "session"           type = "string"
      name = "event_type"        type = "string"
    }
  }

  partition_keys {
    name = "year"  type = "int"
    name = "month" type = "int"
    name = "day"   type = "int"
  }
}

# ── TABLA 4: scan_cycles ───────────────────────────────────────────────────

resource "aws_glue_catalog_table" "scan_cycles" {
  name          = "scan_cycles"
  database_name = aws_glue_catalog_database.audit.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"      = "parquet"
    "parquet.compression" = "SNAPPY"
    "projection.enabled"  = "true"
    "projection.year.type"      = "integer"
    "projection.year.range"     = "2026,2030"
    "projection.month.type"     = "integer"
    "projection.month.range"    = "1,12"
    "projection.month.digits"   = "2"
    "projection.day.type"       = "integer"
    "projection.day.range"      = "1,31"
    "projection.day.digits"     = "2"
    "storage.location.template" = "s3://${var.audit_bucket_name}/scan_cycles/year=$${year}/month=$${month}/day=$${day}/"
  }

  storage_descriptor {
    location      = "s3://${var.audit_bucket_name}/scan_cycles/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters = { "serialization.format" = "1" }
    }

    columns {
      name = "scan_id"                     type = "string"
      name = "timestamp"                   type = "string"
      name = "pares_evaluados"             type = "int"
      name = "pares_operables"             type = "int"
      name = "descartados_trend"           type = "int"
      name = "descartados_volume"          type = "int"
      name = "descartados_volatility"      type = "int"
      name = "descartados_atr"             type = "int"
      name = "descartados_squeeze"         type = "int"
      name = "oportunidades_brutas"        type = "int"
      name = "descartadas_rr"              type = "int"
      name = "descartadas_sl_pct"          type = "int"
      name = "descartadas_cooldown"        type = "int"
      name = "enviadas_telegram"           type = "int"
      name = "duracion_ms"                 type = "int"
      name = "errores"                     type = "int"
      name = "session"                     type = "string"
      name = "event_type"                  type = "string"
    }
  }

  partition_keys {
    name = "year"  type = "int"
    name = "month" type = "int"
    name = "day"   type = "int"
  }
}

# ── TABLA 5: trades ────────────────────────────────────────────────────────

resource "aws_glue_catalog_table" "trades" {
  name          = "trades"
  database_name = aws_glue_catalog_database.audit.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"      = "parquet"
    "parquet.compression" = "SNAPPY"
    "projection.enabled"  = "true"
    "projection.year.type"      = "integer"
    "projection.year.range"     = "2026,2030"
    "projection.month.type"     = "integer"
    "projection.month.range"    = "1,12"
    "projection.month.digits"   = "2"
    "projection.day.type"       = "integer"
    "projection.day.range"      = "1,31"
    "projection.day.digits"     = "2"
    "storage.location.template" = "s3://${var.audit_bucket_name}/trades/year=$${year}/month=$${month}/day=$${day}/"
  }

  storage_descriptor {
    location      = "s3://${var.audit_bucket_name}/trades/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters = { "serialization.format" = "1" }
    }

    columns {
      name = "trade_id"            type = "string"
      name = "opportunity_id"      type = "string"
      name = "mode"                type = "string"
      name = "pair"                type = "string"
      name = "tier"                type = "string"
      name = "strategy"            type = "string"
      name = "timeframe"           type = "string"
      name = "entry_price"         type = "double"
      name = "exit_price"          type = "double"
      name = "sl_initial"          type = "double"
      name = "sl_final"            type = "double"
      name = "sl_type"             type = "string"
      name = "sl_pct"              type = "double"
      name = "tp1_price"           type = "double"
      name = "tp2_price"           type = "double"
      name = "tp1_hit"             type = "boolean"
      name = "trailing_activated"  type = "boolean"
      name = "close_reason"        type = "string"
      name = "gross_pnl"           type = "double"
      name = "net_pnl"             type = "double"
      name = "commission"          type = "double"
      name = "r_multiple"          type = "double"
      name = "rr_planned"          type = "double"
      name = "rr_actual"           type = "double"
      name = "mfe"                 type = "double"
      name = "mae"                 type = "double"
      name = "duration_minutes"    type = "int"
      name = "market_trend"        type = "string"
      name = "market_volatility"   type = "string"
      name = "session"             type = "string"
      name = "confluence"          type = "boolean"
      name = "capital_at_open"     type = "double"
      name = "risk_pct"            type = "double"
      name = "risk_usd"            type = "double"
      name = "position_size_usd"   type = "double"
      name = "started_at"          type = "string"
      name = "ended_at"            type = "string"
      name = "event_type"          type = "string"
    }
  }

  partition_keys {
    name = "year"  type = "int"
    name = "month" type = "int"
    name = "day"   type = "int"
  }
}

# ── GLUE CRAWLER ───────────────────────────────────────────────────────────
# Complementa la proyección de particiones para detectar nuevas tablas o columnas

resource "aws_glue_crawler" "audit" {
  name          = "${var.project_name}-audit-crawler"
  role          = aws_iam_role.glue_crawler.arn
  database_name = aws_glue_catalog_database.audit.name
  description   = "Detecta nuevas particiones y cambios de schema en el bucket de auditoría"

  schedule = var.crawler_schedule

  s3_target {
    path = "s3://${var.audit_bucket_name}/market_context/"
  }
  s3_target {
    path = "s3://${var.audit_bucket_name}/strategy_executions/"
  }
  s3_target {
    path = "s3://${var.audit_bucket_name}/opportunities/"
  }
  s3_target {
    path = "s3://${var.audit_bucket_name}/scan_cycles/"
  }
  s3_target {
    path = "s3://${var.audit_bucket_name}/trades/"
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
```

---

## Athena (`audit/athena.tf`)

```hcl
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
```

---

## CloudWatch Subscription Filters (`audit/cloudwatch.tf`)

```hcl
# Filtro por event_type en los logs JSON de cada Lambda
# Un filtro por tabla para enrutar al Firehose correcto

resource "aws_cloudwatch_log_subscription_filter" "market_context" {
  name            = "${var.project_name}-market-context-filter"
  log_group_name  = var.scanner_log_group_name
  filter_pattern  = "{ $.event_type = \"market_context\" }"
  destination_arn = aws_kinesis_firehose_delivery_stream.market_context.arn
  role_arn        = aws_iam_role.cloudwatch_subscription.arn
  distribution    = "ByLogStream"
}

resource "aws_cloudwatch_log_subscription_filter" "strategy_executions" {
  name            = "${var.project_name}-strategy-executions-filter"
  log_group_name  = var.scanner_log_group_name
  filter_pattern  = "{ $.event_type = \"strategy_execution\" }"
  destination_arn = aws_kinesis_firehose_delivery_stream.strategy_executions.arn
  role_arn        = aws_iam_role.cloudwatch_subscription.arn
  distribution    = "ByLogStream"
}

resource "aws_cloudwatch_log_subscription_filter" "opportunities" {
  name            = "${var.project_name}-opportunities-filter"
  log_group_name  = var.scanner_log_group_name
  filter_pattern  = "{ $.event_type = \"opportunity\" }"
  destination_arn = aws_kinesis_firehose_delivery_stream.opportunities.arn
  role_arn        = aws_iam_role.cloudwatch_subscription.arn
  distribution    = "ByLogStream"
}

resource "aws_cloudwatch_log_subscription_filter" "scan_cycles" {
  name            = "${var.project_name}-scan-cycles-filter"
  log_group_name  = var.scanner_log_group_name
  filter_pattern  = "{ $.event_type = \"scan_cycle\" }"
  destination_arn = aws_kinesis_firehose_delivery_stream.scan_cycles.arn
  role_arn        = aws_iam_role.cloudwatch_subscription.arn
  distribution    = "ByLogStream"
}

resource "aws_cloudwatch_log_subscription_filter" "trades" {
  name            = "${var.project_name}-trades-filter"
  log_group_name  = var.binance_events_log_group_name
  filter_pattern  = "{ $.event_type = \"trade\" }"
  destination_arn = aws_kinesis_firehose_delivery_stream.trades.arn
  role_arn        = aws_iam_role.cloudwatch_subscription.arn
  distribution    = "ByLogStream"
}
```

---

## Queries guardadas en Athena (`audit/saved_queries.tf`)

```hcl
# ── Q1: Embudo del scanner — últimos 7 días ────────────────────────────────

resource "aws_athena_named_query" "embudo_scanner" {
  name        = "01_embudo_scanner_7dias"
  description = "Cuántos pares pasan cada etapa del embudo por día"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    -- EMBUDO DEL SCANNER — últimos 7 días
    -- Muestra cuántos pares pasan cada filtro por día y sesión
    SELECT
        year,
        month,
        day,
        session,
        COUNT(*)                                              AS ciclos,
        ROUND(AVG(pares_evaluados), 1)                        AS avg_pares_evaluados,
        ROUND(AVG(pares_operables), 1)                        AS avg_pares_operables,
        ROUND(AVG(pares_operables * 100.0 / NULLIF(pares_evaluados, 0)), 1) AS pct_pasan_contexto,
        SUM(oportunidades_brutas)                             AS total_ops_brutas,
        SUM(enviadas_telegram)                                AS total_enviadas,
        ROUND(AVG(duracion_ms), 0)                            AS avg_duracion_ms
    FROM scan_cycles
    WHERE year = YEAR(CURRENT_DATE)
        AND month >= MONTH(DATE_ADD('day', -7, CURRENT_DATE))
    GROUP BY year, month, day, session
    ORDER BY year DESC, month DESC, day DESC, total_enviadas DESC;
  SQL
}

# ── Q2: Razones de descarte del contexto ──────────────────────────────────

resource "aws_athena_named_query" "razones_descarte_contexto" {
  name        = "02_razones_descarte_contexto"
  description = "Por qué se descartan los pares en el evaluador de contexto"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    -- RAZONES DE DESCARTE DE CONTEXTO — últimos 7 días
    -- Identifica el cuello de botella principal en el evaluador de mercado
    SELECT
        CASE
            WHEN trend != 'BULLISH'     THEN '1_trend_no_bullish'
            WHEN volume_state = 'QUIET' THEN '2_volumen_bajo'
            WHEN volatility = 'LOW'     THEN '3_volatilidad_baja'
            WHEN NOT atr_viable         THEN '4_atr_no_viable'
            WHEN bb_squeeze             THEN '5_bb_squeeze'
            ELSE 'otro'
        END                                                         AS razon_descarte,
        COUNT(*)                                                     AS total_casos,
        ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1)         AS porcentaje,
        COUNT(DISTINCT pair)                                         AS pares_afectados,
        -- Distribución por sesión
        SUM(CASE WHEN session = 'ASIA'     THEN 1 ELSE 0 END)       AS en_asia,
        SUM(CASE WHEN session = 'LONDON'   THEN 1 ELSE 0 END)       AS en_london,
        SUM(CASE WHEN session = 'NEW_YORK' THEN 1 ELSE 0 END)       AS en_new_york
    FROM market_context_log
    WHERE tradeable = false
        AND year = YEAR(CURRENT_DATE)
        AND month >= MONTH(DATE_ADD('day', -7, CURRENT_DATE))
    GROUP BY 1
    ORDER BY total_casos DESC;
  SQL
}

# ── Q3: Condiciones que fallan por estrategia ─────────────────────────────

resource "aws_athena_named_query" "fallas_por_estrategia" {
  name        = "03_fallas_por_estrategia"
  description = "Qué condición falla más frecuentemente en cada estrategia"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    -- CONDICIONES QUE FALLAN POR ESTRATEGIA — últimos 7 días
    -- Permite identificar si las condiciones son demasiado estrictas
    SELECT
        strategy,
        condicion_falla,
        COUNT(*)                                                          AS total_fallos,
        ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY strategy), 1) AS pct_dentro_estrategia,
        COUNT(DISTINCT pair)                                               AS pares_donde_falla
    FROM strategy_executions
    WHERE resultado = 'FALLO'
        AND condicion_falla IS NOT NULL
        AND year = YEAR(CURRENT_DATE)
        AND month >= MONTH(DATE_ADD('day', -7, CURRENT_DATE))
    GROUP BY strategy, condicion_falla
    ORDER BY strategy, total_fallos DESC;
  SQL
}

# ── Q4: Tasa de conversión por estrategia ─────────────────────────────────

resource "aws_athena_named_query" "conversion_por_estrategia" {
  name        = "04_conversion_por_estrategia"
  description = "Qué porcentaje de ejecuciones genera una oportunidad"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    -- TASA DE CONVERSIÓN POR ESTRATEGIA — últimos 7 días
    -- Si una estrategia tiene < 1% de conversión, sus condiciones son muy estrictas
    -- Si tiene > 30%, puede estar generando señales de baja calidad
    SELECT
        strategy,
        COUNT(*)                                                          AS total_ejecuciones,
        SUM(CASE WHEN resultado = 'OPORTUNIDAD' THEN 1 ELSE 0 END)       AS oportunidades,
        SUM(CASE WHEN resultado = 'FALLO'       THEN 1 ELSE 0 END)       AS fallos,
        SUM(CASE WHEN resultado = 'ERROR'       THEN 1 ELSE 0 END)       AS errores,
        ROUND(SUM(CASE WHEN resultado = 'OPORTUNIDAD' THEN 1.0 ELSE 0.0 END)
              / NULLIF(COUNT(*), 0) * 100, 2)                             AS pct_conversion,
        COUNT(DISTINCT pair)                                               AS pares_evaluados
    FROM strategy_executions
    WHERE year = YEAR(CURRENT_DATE)
        AND month >= MONTH(DATE_ADD('day', -7, CURRENT_DATE))
    GROUP BY strategy
    ORDER BY pct_conversion DESC;
  SQL
}

# ── Q5: Oportunidades por sesión y par ────────────────────────────────────

resource "aws_athena_named_query" "oportunidades_por_sesion" {
  name        = "05_oportunidades_por_sesion_y_par"
  description = "En qué sesión y par se detectan más oportunidades"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    -- OPORTUNIDADES POR SESIÓN Y PAR — últimos 30 días
    -- Identifica qué combinación sesión/par/estrategia es más productiva
    SELECT
        session,
        pair,
        strategy,
        COUNT(*)                                  AS total_oportunidades,
        ROUND(AVG(rr_ratio), 2)                   AS rr_promedio,
        ROUND(AVG(sl_pct) * 100, 3)               AS sl_pct_promedio,
        SUM(CASE WHEN confluence THEN 1 ELSE 0 END) AS con_confluencia
    FROM opportunities
    WHERE year = YEAR(CURRENT_DATE)
        AND month >= MONTH(DATE_ADD('day', -30, CURRENT_DATE))
    GROUP BY session, pair, strategy
    ORDER BY total_oportunidades DESC
    LIMIT 30;
  SQL
}

# ── Q6: Performance de trades — winrate y R múltiple ──────────────────────

resource "aws_athena_named_query" "performance_trades" {
  name        = "06_performance_trades_por_estrategia"
  description = "Winrate, R múltiple promedio y P&L por estrategia"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    -- PERFORMANCE DE TRADES POR ESTRATEGIA — todos los datos
    SELECT
        strategy,
        mode,
        COUNT(*)                                                           AS total_trades,
        SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END)                     AS ganadoras,
        ROUND(AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) AS winrate_pct,
        ROUND(AVG(r_multiple), 2)                                          AS r_multiple_promedio,
        ROUND(SUM(net_pnl), 2)                                             AS pnl_total_usd,
        ROUND(AVG(mae) * 100, 3)                                           AS mae_promedio_pct,
        ROUND(AVG(mfe) * 100, 3)                                           AS mfe_promedio_pct,
        ROUND(AVG(duration_minutes), 0)                                    AS duracion_promedio_min
    FROM trades
    GROUP BY strategy, mode
    ORDER BY mode, r_multiple_promedio DESC;
  SQL
}

# ── Q7: Análisis MAE/MFE para optimizar SL ────────────────────────────────

resource "aws_athena_named_query" "analisis_mae_mfe" {
  name        = "07_analisis_mae_mfe_optimizacion_sl"
  description = "Compara MAE de ganadoras vs SL actual para ver si el SL puede ajustarse"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    -- ANÁLISIS MAE/MFE PARA OPTIMIZAR SL — últimos 30 días
    -- Si MAE promedio de ganadoras < 50% del SL → el SL está demasiado lejos
    -- Si MFE promedio supera TP2 → TP2 puede ser más agresivo
    SELECT
        strategy,
        close_reason,
        COUNT(*)                                  AS trades,
        ROUND(AVG(sl_pct) * 100, 3)              AS sl_pct_promedio,
        ROUND(AVG(mae) * 100, 3)                 AS mae_promedio_pct,
        ROUND(AVG(mae) / NULLIF(AVG(sl_pct), 0) * 100, 1) AS mae_como_pct_del_sl,
        ROUND(AVG(mfe) * 100, 3)                 AS mfe_promedio_pct,
        ROUND(AVG(rr_actual), 2)                 AS rr_actual_promedio,
        ROUND(AVG(rr_planned), 2)                AS rr_planeado_promedio
    FROM trades
    WHERE net_pnl > 0   -- solo ganadoras para el análisis del SL
        AND year = YEAR(CURRENT_DATE)
        AND month >= MONTH(DATE_ADD('day', -30, CURRENT_DATE))
    GROUP BY strategy, close_reason
    ORDER BY strategy, mae_como_pct_del_sl ASC;
  SQL
}

# ── Q8: Correlación confluencia vs winrate ────────────────────────────────

resource "aws_athena_named_query" "confluencia_vs_winrate" {
  name        = "08_confluencia_vs_winrate"
  description = "Las señales con confluencia tienen mejor winrate?"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    -- CONFLUENCIA VS WINRATE
    -- Valida si operar solo con confluencia mejora el resultado
    SELECT
        confluence,
        mode,
        COUNT(*)                                                           AS total_trades,
        ROUND(AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) AS winrate_pct,
        ROUND(AVG(r_multiple), 2)                                          AS r_multiple_promedio,
        ROUND(SUM(net_pnl), 2)                                             AS pnl_total_usd
    FROM trades
    GROUP BY confluence, mode
    ORDER BY mode, confluence DESC;
  SQL
}

# ── Q9: Resumen diario ejecutivo ──────────────────────────────────────────

resource "aws_athena_named_query" "resumen_diario" {
  name        = "09_resumen_diario_ejecutivo"
  description = "Vista rápida del día: oportunidades, trades, P&L"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    -- RESUMEN DIARIO EJECUTIVO
    -- Cambiar year/month/day por la fecha que querés analizar
    WITH contexto AS (
        SELECT
            COUNT(DISTINCT pair)                                              AS pares_evaluados,
            SUM(CASE WHEN tradeable THEN 1 ELSE 0 END)                       AS pares_operables,
            ROUND(AVG(CASE WHEN tradeable THEN 1.0 ELSE 0.0 END) * 100, 1)  AS pct_operables
        FROM market_context_log
        WHERE year = YEAR(CURRENT_DATE)
          AND month = MONTH(CURRENT_DATE)
          AND day = DAY(CURRENT_DATE)
    ),
    ops AS (
        SELECT
            COUNT(*)                                        AS total_oportunidades,
            COUNT(DISTINCT strategy)                        AS estrategias_activas,
            COUNT(DISTINCT pair)                            AS pares_con_oportunidad,
            SUM(CASE WHEN confluence THEN 1 ELSE 0 END)    AS con_confluencia
        FROM opportunities
        WHERE year = YEAR(CURRENT_DATE)
          AND month = MONTH(CURRENT_DATE)
          AND day = DAY(CURRENT_DATE)
    ),
    resultado AS (
        SELECT
            COUNT(*)                                                           AS trades_totales,
            SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END)                     AS ganadoras,
            ROUND(SUM(net_pnl), 2)                                             AS pnl_neto_usd,
            ROUND(AVG(r_multiple), 2)                                          AS r_multiple_avg
        FROM trades
        WHERE year = YEAR(CURRENT_DATE)
          AND month = MONTH(CURRENT_DATE)
          AND day = DAY(CURRENT_DATE)
    )
    SELECT
        c.pares_evaluados,
        c.pares_operables,
        c.pct_operables        AS pct_pasan_contexto,
        o.total_oportunidades,
        o.estrategias_activas,
        o.pares_con_oportunidad,
        o.con_confluencia,
        r.trades_totales,
        r.ganadoras,
        r.pnl_neto_usd,
        r.r_multiple_avg
    FROM contexto c, ops o, resultado r;
  SQL
}

# ── Q10: Detección de estrategias degradadas ──────────────────────────────

resource "aws_athena_named_query" "estrategias_degradadas" {
  name        = "10_deteccion_estrategias_degradadas"
  description = "Alerta si alguna estrategia tiene winrate < 30% o R múltiple < 1 en los últimos 14 días"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    -- DETECCIÓN DE ESTRATEGIAS DEGRADADAS — últimos 14 días
    -- Si winrate < 30% O r_multiple_promedio < 1.0 → revisar la estrategia
    SELECT
        strategy,
        COUNT(*)                                                           AS trades,
        ROUND(AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) AS winrate_pct,
        ROUND(AVG(r_multiple), 2)                                          AS r_multiple_promedio,
        ROUND(SUM(net_pnl), 2)                                             AS pnl_total,
        CASE
            WHEN AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END) < 0.30 THEN '⚠️ WINRATE BAJO'
            WHEN AVG(r_multiple) < 1.0                                     THEN '⚠️ R NEGATIVO'
            ELSE '✅ OK'
        END                                                                AS estado
    FROM trades
    WHERE year = YEAR(CURRENT_DATE)
        AND month >= MONTH(DATE_ADD('day', -14, CURRENT_DATE))
        AND trades >= 5   -- mínimo 5 trades para ser estadísticamente relevante
    GROUP BY strategy
    HAVING COUNT(*) >= 5
    ORDER BY r_multiple_promedio ASC;
  SQL
}
```

---

## Outputs (`outputs.tf`)

```hcl
output "audit_bucket_name" {
  description = "Bucket S3 de auditoría"
  value       = aws_s3_bucket.audit.bucket
}

output "athena_workgroup_name" {
  description = "Workgroup de Athena para queries"
  value       = aws_athena_workgroup.audit.name
}

output "glue_database_name" {
  description = "Base de datos Glue"
  value       = aws_glue_catalog_database.audit.name
}

output "athena_results_bucket" {
  description = "Bucket para resultados de Athena"
  value       = aws_s3_bucket.athena_results.bucket
}

output "firehose_arns" {
  description = "ARNs de los Firehose streams"
  value = {
    market_context      = aws_kinesis_firehose_delivery_stream.market_context.arn
    strategy_executions = aws_kinesis_firehose_delivery_stream.strategy_executions.arn
    opportunities       = aws_kinesis_firehose_delivery_stream.opportunities.arn
    scan_cycles         = aws_kinesis_firehose_delivery_stream.scan_cycles.arn
    trades              = aws_kinesis_firehose_delivery_stream.trades.arn
  }
}
```

---

## Código Python para emitir logs (`src/core/audit.py`)

Este módulo debe crearse en el proyecto Python existente.
Los Lambdas lo importan y llaman a estas funciones.
Los logs JSON van a CloudWatch y los subscription filters los enrutan a Firehose.

```python
# src/core/audit.py
import json
import logging
import uuid
from datetime import datetime, timezone
from dataclasses import asdict

logger = logging.getLogger()


def _session() -> str:
    """Determina la sesión de mercado actual según hora UTC."""
    hora = datetime.now(timezone.utc).hour
    if 0 <= hora < 8:
        return "ASIA"
    elif 8 <= hora < 13:
        return "LONDON"
    elif 13 <= hora < 17:
        return "OVERLAP"
    else:
        return "NEW_YORK"


def log_market_context(scan_id: str, ctx, valores: dict) -> None:
    """
    Emitir log de contexto de mercado.
    Llamar una vez por par en cada ciclo del scanner.
    """
    logger.info(json.dumps({
        "event_type":   "market_context",
        "scan_id":      scan_id,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "session":      _session(),
        "pair":         ctx.pair,
        "tier":         getattr(ctx, "tier", "1"),
        "trend":        ctx.trend,
        "volatility":   ctx.volatility,
        "volume_state": ctx.volume_state,
        "atr_viable":   ctx.atr_viable,
        "bb_squeeze":   ctx.bb_squeeze,
        "tradeable":    ctx.tradeable,
        **valores
    }))


def log_strategy_execution(
    scan_id: str,
    pair: str,
    strategy: str,
    resultado: str,             # "OPORTUNIDAD" | "FALLO" | "ERROR"
    condicion_falla: str = None,
    valor_condicion: str = None,
    opp: dict = None
) -> None:
    """
    Emitir log de ejecución de estrategia.
    Llamar por cada estrategia evaluada (tanto si genera oportunidad como si no).
    """
    logger.info(json.dumps({
        "event_type":       "strategy_execution",
        "scan_id":          scan_id,
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "session":          _session(),
        "pair":             pair,
        "strategy":         strategy,
        "resultado":        resultado,
        "condicion_falla":  condicion_falla,
        "valor_condicion":  valor_condicion,
        **(opp or {})
    }))


def log_opportunity(scan_id: str, opp) -> None:
    """
    Emitir log de oportunidad generada y enviada a Telegram.
    Llamar solo cuando la oportunidad pasa todos los filtros.
    """
    logger.info(json.dumps({
        "event_type":        "opportunity",
        "scan_id":           scan_id,
        "timestamp":         datetime.now(timezone.utc).isoformat(),
        "session":           _session(),
        "opportunity_id":    str(uuid.uuid4()),
        "pair":              opp.pair,
        "tier":              getattr(opp, "tier", "1"),
        "strategy":          opp.strategy,
        "timeframe":         opp.timeframe,
        "entry_price":       opp.entry_price,
        "sl_price":          opp.sl_price,
        "sl_pct":            opp.sl_pct,
        "sl_type":           getattr(opp, "sl_type", ""),
        "tp1_price":         opp.tp1_price,
        "tp2_price":         opp.tp2_price,
        "rr_ratio":          opp.rr_ratio,
        "risk_usd":          opp.risk_usd,
        "position_size_usd": opp.position_size_usd,
        "confluence":        opp.confluence,
        "drift_pct":         getattr(opp, "slippage_pct", 0.0),
    }))


def log_scan_cycle(scan_id: str, metricas: dict, duracion_ms: int) -> None:
    """
    Emitir log resumen del ciclo completo del scanner.
    Llamar una vez al final de cada ejecución del Lambda scanner.
    """
    logger.info(json.dumps({
        "event_type":  "scan_cycle",
        "scan_id":     scan_id,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "session":     _session(),
        "duracion_ms": duracion_ms,
        **metricas
    }))


def log_trade(trade) -> None:
    """
    Emitir log de trade cerrado con metadata completa.
    Llamar desde BinanceEventsLambda (REAL) y PositionMonitorLambda (SIM).
    """
    logger.info(json.dumps({
        "event_type":           "trade",
        "timestamp":            datetime.now(timezone.utc).isoformat(),
        "session":              _session(),
        "trade_id":             trade.trade_id,
        "opportunity_id":       getattr(trade, "opportunity_id", ""),
        "mode":                 trade.mode,
        "pair":                 trade.pair,
        "tier":                 getattr(trade, "tier", "1"),
        "strategy":             trade.strategy,
        "timeframe":            trade.timeframe,
        "entry_price":          trade.entry_price,
        "exit_price":           trade.exit_price,
        "sl_initial":           trade.sl_initial,
        "sl_final":             trade.sl_final,
        "sl_type":              getattr(trade, "sl_type", ""),
        "sl_pct":               trade.sl_pct,
        "tp1_price":            trade.tp1_price,
        "tp2_price":            trade.tp2_price,
        "tp1_hit":              trade.tp1_hit,
        "trailing_activated":   trade.trailing_activated,
        "close_reason":         trade.close_reason,
        "gross_pnl":            trade.gross_pnl_usd,
        "net_pnl":              trade.net_pnl_usd,
        "commission":           trade.commission_usd,
        "r_multiple":           trade.r_multiple,
        "rr_planned":           trade.rr_ratio_planned,
        "rr_actual":            trade.rr_ratio_actual,
        "mfe":                  trade.max_favorable_excursion,
        "mae":                  trade.max_adverse_excursion,
        "duration_minutes":     trade.duration_minutes,
        "market_trend":         trade.market_trend,
        "market_volatility":    trade.market_volatility,
        "confluence":           trade.confluence,
        "capital_at_open":      trade.capital_at_open,
        "risk_pct":             trade.risk_pct,
        "risk_usd":             trade.risk_usd,
        "position_size_usd":    trade.position_size_usd,
        "started_at":           trade.started_at,
        "ended_at":             trade.ended_at,
    }))
```

---

## Instrucciones para Cursor

1. Crear todos los archivos de Terraform en `infra/audit/`
2. Crear `src/core/audit.py` con el módulo Python
3. Importar y llamar las funciones de `audit.py` en:
   - `src/core/market_context.py` → llamar `log_market_context()` al final de `evaluate()`
   - `src/strategies/base.py` → llamar `log_strategy_execution()` en `_check_conditions()`
   - `src/lambdas/scanner/handler.py` → llamar `log_opportunity()` y `log_scan_cycle()`
   - `src/lambdas/binance_events/handler.py` → llamar `log_trade()` al cerrar REAL
   - `src/lambdas/position_monitor/handler.py` → llamar `log_trade()` al cerrar SIM

4. Ejecutar en orden:
   ```bash
   cd infra
   terraform init
   terraform plan -out=tfplan
   terraform apply tfplan
   ```

5. Verificar que los subscription filters están activos:
   ```bash
   aws logs describe-subscription-filters \
     --log-group-name /aws/lambda/trading-bot-scanner
   ```

6. Para validar que los datos llegan a S3, esperar 2-3 ciclos del scanner
   y verificar:
   ```bash
   aws s3 ls s3://trading-bot-audit/market_context/ --recursive | head -20
   ```

7. Abrir Athena en la consola AWS, seleccionar workgroup `trading-bot-audit`
   y ejecutar la query `09_resumen_diario_ejecutivo` para validar el pipeline completo.

---

## Costo estimado mensual

```
Firehose:      ~50MB logs/día × 30 días → 1.5GB → $0.04/mes
S3 storage:    Parquet SNAPPY ~10x compresión → 150MB → $0.003/mes
S3 requests:   ~1,500 PutObject/mes → $0.007/mes
Glue Crawler:  1 corrida/día × ~6 min → $0.013/mes
Athena:        Con particiones año/mes/día el scan real es ~5-10MB/query
               100 queries/mes × 10MB = 1GB → $0.005/mes
───────────────────────────────────────────────────────
TOTAL:         ~$0.07/mes
```

---

*Pipeline de auditoría de nivel enterprise por menos de 10 centavos por mes.*
*Las particiones año/mes/día garantizan que Athena escanea solo los datos necesarios.*
*La proyección de particiones en Glue elimina la dependencia del crawler para queries.*
