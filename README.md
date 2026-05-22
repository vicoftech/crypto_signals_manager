# Trading Opportunity Bot

Implementacion inicial del bot de oportunidades para Binance Spot con Telegram y AWS Lambda.

Este proyecto se despliega con Terraform (estado remoto en S3 + lock en DynamoDB).

## Estructura

- `src/lambdas/scanner/handler.py`: scanner cada 5 minutos.
- `src/lambdas/position_monitor/handler.py`: monitor de simulaciones cada minuto.
- `src/lambdas/webhook/handler.py`: entrada de comandos/callbacks Telegram.
- `src/lambdas/binance_events/handler.py`: eventos de Binance para modo REAL.
- `src/lambdas/keepalive/handler.py`: renovacion periodica de listenKey.

## Setup local

1. Crear entorno virtual Python 3.12.
2. Instalar dependencias:
   - `pip install -r requirements.txt`
3. Ejecutar tests:
   - `pytest -q`

## Variables requeridas

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `AWS_PROFILE=asap_main`

Para fase SIM no necesitas `BINANCE_API_KEY` ni `BINANCE_SECRET` (solo endpoints publicos).
Para fase LIVE TEST/REAL define tambien:
- `BINANCE_SECRET_NAME_TEST` (ej: `crypto-trading-bot/binance-test`)
- `BINANCE_SECRET_NAME_LIVE` (ej: `crypto-trading-bot/binance-live`)
- `BINANCE_ENV` (`test_live`/`live_test`/`testnet` o `live`)

Se espera un secreto JSON en AWS Secrets Manager con este formato:

```json
{
  "api_key": "xxxx",
  "api_secret": "yyyy",
  "env": "testnet"
}
```

Seleccion de secreto:
- si `BINANCE_ENV` es `test_live`, `live_test` o `testnet` -> usa `BINANCE_SECRET_NAME_TEST`
- si `BINANCE_ENV` es `live` -> usa `BINANCE_SECRET_NAME_LIVE`

## Comandos para probar el bot

### 1) Verificar infraestructura desplegada

```bash
aws lambda list-functions \
  --profile asap_main \
  --region ap-northeast-1 \
  --query "Functions[?starts_with(FunctionName, 'crypto-trading-bot-')].FunctionName" \
  --output text
```

```bash
aws events list-rules \
  --profile asap_main \
  --region ap-northeast-1 \
  --query "Rules[?starts_with(Name, 'crypto-trading-bot-')].[Name,ScheduleExpression]" \
  --output table
```

### 2) Probar scanner manualmente

```bash
aws lambda invoke \
  --profile asap_main \
  --region ap-northeast-1 \
  --function-name crypto-trading-bot-scanner \
  --payload '{}' \
  /tmp/scanner_out.json && cat /tmp/scanner_out.json
```

### 3) Probar monitor de simulacion manualmente

```bash
aws lambda invoke \
  --profile asap_main \
  --region ap-northeast-1 \
  --function-name crypto-trading-bot-position-monitor \
  --payload '{}' \
  /tmp/monitor_out.json && cat /tmp/monitor_out.json
```

### 4) Probar webhook manualmente

```bash
aws lambda invoke \
  --profile asap_main \
  --region ap-northeast-1 \
  --function-name crypto-trading-bot-webhook \
  --payload '{"test":"ping"}' \
  /tmp/webhook_out.json && cat /tmp/webhook_out.json
```

### 5) Ver logs en tiempo real

```bash
aws logs tail /aws/lambda/crypto-trading-bot-scanner \
  --profile asap_main \
  --region ap-northeast-1 \
  --follow
```

```bash
aws logs tail /aws/lambda/crypto-trading-bot-position-monitor \
  --profile asap_main \
  --region ap-northeast-1 \
  --follow
```

### 6) Forzar nueva version de codigo (rebuild + apply)

```bash
rm -rf build/package build/lambda_bundle.zip
mkdir -p build/package
pip3 install -r requirements.txt -t build/package
cp -R src build/package/src
cd build/package && zip -qr ../lambda_bundle.zip . && cd ../..
```

```bash
cd infra/terraform/app
AWS_PROFILE=asap_main terraform apply -auto-approve \
  -var="telegram_bot_token=TU_TOKEN" \
  -var="telegram_chat_id=TU_CHAT_ID"
```

### 7) Ver parametros SSM configurados

```bash
aws ssm get-parameters \
  --profile asap_main \
  --region ap-northeast-1 \
  --names /trading-bot/TELEGRAM_CHAT_ID /trading-bot/TELEGRAM_BOT_TOKEN \
  --with-decryption
```

## Deploy (Terraform)

- Bootstrap de estado remoto:
  - `cd infra/terraform/state`
  - `AWS_PROFILE=asap_main terraform init`
  - `AWS_PROFILE=asap_main terraform apply -auto-approve`
- **OIDC GitHub (una vez):** `infra/terraform/github-oidc` → ver `docs/CI_DEPLOY.md`
- Deploy de app (local):
  - `bash scripts/build_lambda_bundle.sh`
  - `cd infra/terraform/app`
  - `AWS_PROFILE=asap_main terraform init -backend-config=backends/local.hcl`
  - `AWS_PROFILE=asap_main terraform apply -auto-approve -var="telegram_bot_token=TU_TOKEN" -var="telegram_chat_id=TU_CHAT_ID"`
- **CI:** push a `main` ejecuta `.github/workflows/deploy.yml` (requiere secrets `AWS_ROLE_ARN`, Telegram).

## Nota

Esta version deja el esqueleto funcional para scanner, contexto, filtros, calculadora y simulador.  
Webhook Telegram y reconciliacion de eventos Binance estan en modo base (placeholder) para completar en siguiente iteracion.

## Migracion de modos de trades

Para normalizar historico a los nuevos modos (`simulation`, `live_test`, `live`):

```bash
AWS_PROFILE=asap_main AWS_REGION=ap-northeast-1 \
python scripts/migrate_trade_modes.py
```
