# Auditoría analítica (Firehose → S3 Parquet → Glue → Athena)

Terraform en `infra/audit/` despliega el pipeline descrito en `features/cursor-prompt-auditoria-terraform.md`.

## Requisitos

- Perfil AWS (`asap_main`) con permisos para crear S3, IAM, Glue, Kinesis Firehose, Athena, CloudWatch.
- Los nombres de bucket por defecto incluyen el **account ID** para unicidad global.

## Despliegue

```bash
cd infra/audit
AWS_PROFILE=asap_main terraform init
AWS_PROFILE=asap_main terraform plan -out=tfplan
AWS_PROFILE=asap_main terraform apply tfplan
```

## Uso

- **Athena**: consola AWS → Athena → workgroup `trading-bot-audit` (o el valor de `project_name`), base `trading_bot_audit`.
- **Queries guardadas**: recursos `aws_athena_named_query` (prefijos `01_` … `10_`).
- **S3**: prefijos `market_context/`, `strategy_executions/`, `opportunities/`, `scan_cycles/`, `trades/` bajo el bucket de auditoría.

## Logs de aplicación

Las Lambdas envían eventos JSON a **Kinesis Firehose** con `PutRecord` (`src/core/audit.py`), usando el mismo esquema que las tablas Glue. Sigue habiendo una línea en CloudWatch vía `logger.info` para depuración operativa, pero el pipeline analítico no depende de subscription filters.

Las variables de entorno `AUDIT_FIREHOSE_*` las define Terraform en `infra/terraform/app` (prefijo alineado con `project_name` en este módulo).

## Verificación

```bash
aws s3 ls "s3://$(terraform output -raw audit_bucket_name)/market_context/" --recursive | head -20
```

(Ejecutar `terraform output` desde `infra/audit` tras el apply.)
