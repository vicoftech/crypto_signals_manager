variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
}

variable "aws_profile" {
  type    = string
  default = "asap_main"
}

variable "telegram_bot_token" {
  type      = string
  sensitive = true
}

variable "telegram_chat_id" {
  type = string
}

variable "lambda_zip_path" {
  type    = string
  default = "../../../build/lambda_bundle.zip"
}

variable "artifact_bucket" {
  type    = string
  default = "crypto-trading-bot-tfstate-913123310997"
}

variable "artifact_key" {
  type    = string
  default = "lambda/lambda_bundle.zip"
}

variable "audit_firehose_prefix" {
  type        = string
  default     = "trading-bot"
  description = "Prefijo de nombres de Kinesis Firehose (debe coincidir con project_name en infra/audit)."
}

variable "binance_env" {
  type        = string
  default     = "test_live"
  description = "Entorno Binance: test_live/live_test/testnet | live"
}

variable "binance_secret_name_test" {
  type        = string
  default     = "crypto-trading-bot/binance-test"
  description = "Secret de testnet/live_test en AWS Secrets Manager."
}

variable "binance_secret_name_live" {
  type        = string
  default     = "crypto-trading-bot/binance-live"
  description = "Secret de producción live en AWS Secrets Manager."
}
