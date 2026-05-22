output "github_oidc_provider_arn" {
  value       = aws_iam_openid_connect_provider.github.arn
  description = "ARN del OIDC provider (referencia)."
}

output "deploy_role_arn" {
  value       = aws_iam_role.github_deploy.arn
  description = "Configurar en GitHub secret AWS_ROLE_ARN"
}

output "deploy_role_name" {
  value = aws_iam_role.github_deploy.name
}

output "github_repository_setting_hint" {
  value = <<-EOT
    GitHub repo: ${var.github_org}/${var.github_repo}
    Branches permitidas: ${join(", ", var.github_branches)}

    Secrets en el repositorio (Settings → Secrets → Actions):
      AWS_ROLE_ARN = ${aws_iam_role.github_deploy.arn}
      TELEGRAM_BOT_TOKEN = (token del bot)
      TELEGRAM_CHAT_ID = (chat id)

    No hace falta AWS_ACCESS_KEY_ID: el workflow usa OIDC.
  EOT
}
