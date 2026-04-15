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
