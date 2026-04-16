terraform {
  required_version = ">= 1.5.0"

  backend "s3" {
    bucket         = "crypto-trading-bot-tfstate-913123310997"
    key            = "app/terraform.tfstate"
    region         = "ap-northeast-1"
    dynamodb_table = "crypto-trading-bot-tflock"
    profile        = "asap_main"
    encrypt        = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "lambda_exec" {
  name = "crypto-trading-bot-lambda-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "basic_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "bot_inline" {
  name = "crypto-trading-bot-inline"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:PutParameter"
        ]
        Effect   = "Allow"
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/trading-bot/*"
      },
      {
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Scan",
          "dynamodb:Query"
        ]
        Effect = "Allow"
        Resource = [
          aws_dynamodb_table.pairs.arn,
          aws_dynamodb_table.config.arn,
          aws_dynamodb_table.trades.arn
        ]
      },
      {
        Action = [
          "lambda:InvokeFunction"
        ]
        Effect   = "Allow"
        Resource = "*"
      },
      {
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams"
        ]
        Effect   = "Allow"
        Resource = "*"
      },
      {
        Action = [
          "firehose:PutRecord",
          "firehose:PutRecordBatch"
        ]
        Effect = "Allow"
        Resource = [
          "arn:aws:firehose:${var.aws_region}:${data.aws_caller_identity.current.account_id}:deliverystream/${var.audit_firehose_prefix}-*"
        ]
      }
    ]
  })
}

resource "aws_dynamodb_table" "pairs" {
  name         = "crypto-trading-bot-pairs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pair"
  attribute {
    name = "pair"
    type = "S"
  }
}

resource "aws_dynamodb_table" "config" {
  name         = "crypto-trading-bot-config"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "key"
  attribute {
    name = "key"
    type = "S"
  }
}

resource "aws_dynamodb_table" "trades" {
  name         = "crypto-trading-bot-trades"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "trade_id"
  attribute {
    name = "trade_id"
    type = "S"
  }
}

resource "aws_dynamodb_table_item" "pairs_btc" {
  table_name = aws_dynamodb_table.pairs.name
  hash_key   = aws_dynamodb_table.pairs.hash_key
  item = jsonencode({
    pair                  = { S = "BTCUSDT" }
    active                = { BOOL = true }
    tier                  = { S = "1" }
    auto_trade            = { BOOL = true }
    auto_trade_strategies = { L = [{ S = "EMAPullback" }, { S = "RangeBreakout" }, { S = "SupportBounce" }, { S = "MACDCross" }, { S = "ORB" }, { S = "Momentum" }] }
    strategies            = { L = [{ S = "EMAPullback" }, { S = "RangeBreakout" }, { S = "SupportBounce" }, { S = "MACDCross" }, { S = "ORB" }, { S = "Momentum" }] }
  })
}

resource "aws_dynamodb_table_item" "pairs_eth" {
  table_name = aws_dynamodb_table.pairs.name
  hash_key   = aws_dynamodb_table.pairs.hash_key
  item = jsonencode({
    pair                  = { S = "ETHUSDT" }
    active                = { BOOL = true }
    tier                  = { S = "1" }
    auto_trade            = { BOOL = true }
    auto_trade_strategies = { L = [{ S = "EMAPullback" }, { S = "RangeBreakout" }, { S = "SupportBounce" }, { S = "MACDCross" }, { S = "ORB" }, { S = "Momentum" }] }
    strategies            = { L = [{ S = "EMAPullback" }, { S = "RangeBreakout" }, { S = "SupportBounce" }, { S = "MACDCross" }, { S = "ORB" }, { S = "Momentum" }] }
  })
}

resource "aws_dynamodb_table_item" "cfg_capital" {
  table_name = aws_dynamodb_table.config.name
  hash_key   = aws_dynamodb_table.config.hash_key
  item = jsonencode({
    key   = { S = "capital_total" }
    value = { N = "1183.0" }
  })
}

resource "aws_dynamodb_table_item" "cfg_risk" {
  table_name = aws_dynamodb_table.config.name
  hash_key   = aws_dynamodb_table.config.hash_key
  item = jsonencode({
    key   = { S = "risk_pct" }
    value = { N = "0.05" }
  })
}

resource "aws_dynamodb_table_item" "cfg_paused" {
  table_name = aws_dynamodb_table.config.name
  hash_key   = aws_dynamodb_table.config.hash_key
  item = jsonencode({
    key   = { S = "scanner_paused" }
    value = { BOOL = false }
  })
}

resource "aws_ssm_parameter" "telegram_bot_token" {
  name  = "/trading-bot/TELEGRAM_BOT_TOKEN"
  type  = "SecureString"
  value = var.telegram_bot_token
}

resource "aws_ssm_parameter" "telegram_chat_id" {
  name  = "/trading-bot/TELEGRAM_CHAT_ID"
  type  = "String"
  value = var.telegram_chat_id
}

locals {
  audit_firehose = {
    market_context      = "${var.audit_firehose_prefix}-market-context"
    strategy_executions = "${var.audit_firehose_prefix}-strategy-executions"
    opportunities       = "${var.audit_firehose_prefix}-opportunities"
    scan_cycles         = "${var.audit_firehose_prefix}-scan-cycles"
    trades              = "${var.audit_firehose_prefix}-trades"
  }

  lambda_env = {
    CAPITAL_TOTAL        = "1183.0"
    RISK_PER_TRADE_PCT   = "0.05"
    MIN_RR_RATIO         = "2.5"
    MAX_SL_PCT           = "0.02"
    TRAILING_ACTIVATION  = "1.0"
    TRAILING_STEP_PCT    = "0.005"
    ENTRY_DRIFT_MAX_PCT  = "0.003"
    COOLDOWN_MINUTES     = "45"
    TELEGRAM_BOT_TOKEN   = var.telegram_bot_token
    TELEGRAM_CHAT_ID     = var.telegram_chat_id
    BINANCE_API_KEY      = ""
    BINANCE_SECRET       = ""
    PAIRS_TABLE_NAME     = aws_dynamodb_table.pairs.name
    CONFIG_TABLE_NAME    = aws_dynamodb_table.config.name
    TRADES_TABLE_NAME    = aws_dynamodb_table.trades.name
    AUDIT_FIREHOSE_MARKET_CONTEXT      = local.audit_firehose.market_context
    AUDIT_FIREHOSE_STRATEGY_EXECUTIONS = local.audit_firehose.strategy_executions
    AUDIT_FIREHOSE_OPPORTUNITIES       = local.audit_firehose.opportunities
    AUDIT_FIREHOSE_SCAN_CYCLES         = local.audit_firehose.scan_cycles
    AUDIT_FIREHOSE_TRADES              = local.audit_firehose.trades
  }
}

resource "aws_s3_object" "lambda_bundle" {
  bucket = var.artifact_bucket
  key    = var.artifact_key
  source = var.lambda_zip_path
  etag   = filemd5(var.lambda_zip_path)
}

resource "aws_lambda_function" "scanner" {
  function_name    = "crypto-trading-bot-scanner"
  role             = aws_iam_role.lambda_exec.arn
  runtime          = "python3.12"
  handler          = "src.lambdas.scanner.handler.handler"
  s3_bucket        = var.artifact_bucket
  s3_key           = aws_s3_object.lambda_bundle.key
  source_code_hash = filebase64sha256(var.lambda_zip_path)
  timeout          = 60
  memory_size      = 256
  environment { variables = local.lambda_env }
}

resource "aws_lambda_function" "position_monitor" {
  function_name    = "crypto-trading-bot-position-monitor"
  role             = aws_iam_role.lambda_exec.arn
  runtime          = "python3.12"
  handler          = "src.lambdas.position_monitor.handler.handler"
  s3_bucket        = var.artifact_bucket
  s3_key           = aws_s3_object.lambda_bundle.key
  source_code_hash = filebase64sha256(var.lambda_zip_path)
  timeout          = 58
  memory_size      = 128
  environment { variables = local.lambda_env }
}

resource "aws_lambda_function" "webhook" {
  function_name    = "crypto-trading-bot-webhook"
  role             = aws_iam_role.lambda_exec.arn
  runtime          = "python3.12"
  handler          = "src.lambdas.webhook.handler.handler"
  s3_bucket        = var.artifact_bucket
  s3_key           = aws_s3_object.lambda_bundle.key
  source_code_hash = filebase64sha256(var.lambda_zip_path)
  timeout          = 15
  memory_size      = 128
  environment { variables = local.lambda_env }
}

resource "aws_lambda_function" "binance_events" {
  function_name    = "crypto-trading-bot-binance-events"
  role             = aws_iam_role.lambda_exec.arn
  runtime          = "python3.12"
  handler          = "src.lambdas.binance_events.handler.handler"
  s3_bucket        = var.artifact_bucket
  s3_key           = aws_s3_object.lambda_bundle.key
  source_code_hash = filebase64sha256(var.lambda_zip_path)
  timeout          = 15
  memory_size      = 128
  environment { variables = local.lambda_env }
}

resource "aws_lambda_function" "keepalive" {
  function_name    = "crypto-trading-bot-keepalive"
  role             = aws_iam_role.lambda_exec.arn
  runtime          = "python3.12"
  handler          = "src.lambdas.keepalive.handler.handler"
  s3_bucket        = var.artifact_bucket
  s3_key           = aws_s3_object.lambda_bundle.key
  source_code_hash = filebase64sha256(var.lambda_zip_path)
  timeout          = 10
  memory_size      = 128
  environment { variables = local.lambda_env }
}

resource "aws_cloudwatch_log_group" "scanner_logs" {
  name              = "/aws/lambda/${aws_lambda_function.scanner.function_name}"
  retention_in_days = 1
}

resource "aws_cloudwatch_log_group" "position_monitor_logs" {
  name              = "/aws/lambda/${aws_lambda_function.position_monitor.function_name}"
  retention_in_days = 1
}

resource "aws_cloudwatch_log_group" "webhook_logs" {
  name              = "/aws/lambda/${aws_lambda_function.webhook.function_name}"
  retention_in_days = 1
}

resource "aws_cloudwatch_log_group" "binance_events_logs" {
  name              = "/aws/lambda/${aws_lambda_function.binance_events.function_name}"
  retention_in_days = 1
}

resource "aws_cloudwatch_log_group" "keepalive_logs" {
  name              = "/aws/lambda/${aws_lambda_function.keepalive.function_name}"
  retention_in_days = 1
}

resource "aws_cloudwatch_event_rule" "scanner_rule" {
  name                = "crypto-trading-bot-scanner-5m"
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "scanner_target" {
  rule      = aws_cloudwatch_event_rule.scanner_rule.name
  target_id = "scanner-lambda"
  arn       = aws_lambda_function.scanner.arn
}

resource "aws_lambda_permission" "scanner_events" {
  statement_id  = "AllowExecutionFromEventBridgeScanner"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scanner.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.scanner_rule.arn
}

resource "aws_cloudwatch_event_rule" "position_monitor_rule" {
  name                = "crypto-trading-bot-position-monitor-1m"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "position_monitor_target" {
  rule      = aws_cloudwatch_event_rule.position_monitor_rule.name
  target_id = "position-monitor-lambda"
  arn       = aws_lambda_function.position_monitor.arn
}

resource "aws_lambda_permission" "position_monitor_events" {
  statement_id  = "AllowExecutionFromEventBridgePositionMonitor"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.position_monitor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.position_monitor_rule.arn
}

resource "aws_cloudwatch_event_rule" "keepalive_rule" {
  name                = "crypto-trading-bot-keepalive-30m"
  schedule_expression = "rate(30 minutes)"
}

resource "aws_cloudwatch_event_target" "keepalive_target" {
  rule      = aws_cloudwatch_event_rule.keepalive_rule.name
  target_id = "keepalive-lambda"
  arn       = aws_lambda_function.keepalive.arn
}

resource "aws_lambda_permission" "keepalive_events" {
  statement_id  = "AllowExecutionFromEventBridgeKeepAlive"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.keepalive.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.keepalive_rule.arn
}

resource "aws_apigatewayv2_api" "webhook_api" {
  name          = "crypto-trading-bot-webhook-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "webhook_integration" {
  api_id                 = aws_apigatewayv2_api.webhook_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.webhook.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "webhook_route" {
  api_id    = aws_apigatewayv2_api.webhook_api.id
  route_key = "POST /webhook"
  target    = "integrations/${aws_apigatewayv2_integration.webhook_integration.id}"
}

resource "aws_apigatewayv2_stage" "webhook_stage" {
  api_id      = aws_apigatewayv2_api.webhook_api.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "allow_apigw_webhook" {
  statement_id  = "AllowInvokeFromHttpApiWebhook"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.webhook.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook_api.execution_arn}/*/*"
}

output "scanner_lambda_name" {
  value = aws_lambda_function.scanner.function_name
}

output "webhook_url" {
  value = "${aws_apigatewayv2_stage.webhook_stage.invoke_url}/webhook"
}
