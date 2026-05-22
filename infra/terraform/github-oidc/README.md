# GitHub Actions OIDC → AWS

Bootstrap **una vez** con credenciales locales (perfil `asap_main`):

```bash
cd infra/terraform/github-oidc
AWS_PROFILE=asap_main terraform init
AWS_PROFILE=asap_main terraform apply
```

Copia el output `deploy_role_arn` y configúralo en el repo de GitHub:

**Settings → Secrets and variables → Actions → New repository secret**

| Secret | Valor |
|--------|--------|
| `AWS_ROLE_ARN` | output `deploy_role_arn` |
| `TELEGRAM_BOT_TOKEN` | token del bot |
| `TELEGRAM_CHAT_ID` | chat id |

El workflow `.github/workflows/deploy.yml` asume este rol vía OIDC al push en `main`.

## Ampliar ramas, environments o repos

Si el workflow usa `environment: main` en GitHub Actions, el claim OIDC es
`repo:ORG/REPO:environment:main` (incluido en `github_environments` por defecto).

Edita `github_branches`, `github_environments`, `github_org` / `github_repo` y vuelve a aplicar.

## Nota

Si el OIDC provider de GitHub ya existe en la cuenta, importa o comenta el recurso:

```bash
terraform import aws_iam_openid_connect_provider.github \
  arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com
```
