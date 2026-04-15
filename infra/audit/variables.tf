variable "aws_region" {
  description = "Región AWS del proyecto"
  type        = string
  default     = "ap-northeast-1"
}

variable "aws_profile" {
  type    = string
  default = "asap_main"
}

variable "environment" {
  description = "Ambiente: dev, staging, prod"
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Prefijo para todos los recursos"
  type        = string
  default     = "trading-bot"
}

variable "audit_bucket_name" {
  description = "Nombre del bucket S3 de auditoría (debe ser globalmente único)"
  type        = string
  default     = ""
}

variable "glue_database_name" {
  description = "Nombre de la base de datos en Glue"
  type        = string
  default     = "trading_bot_audit"
}

variable "athena_results_bucket" {
  description = "Bucket para resultados de queries de Athena"
  type        = string
  default     = ""
}

variable "firehose_buffer_size_mb" {
  description = "MB antes de flush a S3 (mínimo 64 si hay conversión Parquet)"
  type        = number
  default     = 64
}

variable "firehose_buffer_interval_seconds" {
  description = "Segundos máximos antes de hacer flush"
  type        = number
  default     = 60
}

variable "logs_retention_days" {
  description = "Días de retención en CloudWatch (referencia; grupos de log de Lambdas existentes)"
  type        = number
  default     = 7
}

variable "s3_glacier_transition_days" {
  description = "Días hasta mover a Glacier"
  type        = number
  default     = 90
}

variable "crawler_schedule" {
  description = "Cron para el Glue Crawler (UTC)"
  type        = string
  default     = "cron(30 0 * * ? *)"
}

variable "scanner_log_group_name" {
  type    = string
  default = "/aws/lambda/crypto-trading-bot-scanner"
}

variable "monitor_log_group_name" {
  type    = string
  default = "/aws/lambda/crypto-trading-bot-position-monitor"
}

variable "binance_events_log_group_name" {
  type    = string
  default = "/aws/lambda/crypto-trading-bot-binance-events"
}
