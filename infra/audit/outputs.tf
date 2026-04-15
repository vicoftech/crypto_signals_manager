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
