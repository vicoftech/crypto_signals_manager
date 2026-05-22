# CI/CD — GitHub Actions + OIDC

## 1. Bootstrap del rol OIDC (una vez, local)

```bash
cd infra/terraform/github-oidc
AWS_PROFILE=asap_main terraform init
AWS_PROFILE=asap_main terraform apply
```

Anota `deploy_role_arn`.

## 2. Secrets en GitHub (environment `main`)

Repositorio: `vicoftech/crypto_signals_manager` → **Settings → Environments → main → Environment secrets**

| Secret | Descripción |
|--------|-------------|
| `AWS_ROLE_ARN` | ARN del rol (`deploy_role_arn`) |
| `TELEGRAM_BOT_TOKEN` | Bot Telegram (Terraform app) |
| `TELEGRAM_CHAT_ID` | Chat id |

Los workflows usan `environment: main`. También sirven como **repository secrets** si preferís no usar environments.

No configures `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.

## 3. Qué hace el pipeline

| Evento | Workflow | Acción |
|--------|----------|--------|
| Push a `main` | `deploy.yml` | Build `lambda_bundle.zip` → `terraform apply` en `infra/terraform/app` |
| Pull request | `terraform-plan.yml` | Build + `terraform plan` (comentario en el PR) |

## 4. Terraform local (después del cambio de backend)

```bash
cd infra/terraform/app
AWS_PROFILE=asap_main terraform init -backend-config=backends/local.hcl
AWS_PROFILE=asap_main terraform apply \
  -var="telegram_bot_token=..." \
  -var="telegram_chat_id=..."
```

## 5. Reconfigurar init si ya tenías `.terraform`

```bash
cd infra/terraform/app
terraform init -reconfigure -backend-config=backends/local.hcl
```
