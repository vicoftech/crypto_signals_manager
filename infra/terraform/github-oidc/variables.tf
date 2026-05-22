variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
}

variable "aws_profile" {
  type        = string
  default     = "asap_main"
  description = "Perfil local para el bootstrap (apply una vez). CI usa OIDC, no perfil."
}

variable "github_org" {
  type        = string
  default     = "vicoftech"
  description = "Organizacion o usuario de GitHub."
}

variable "github_repo" {
  type        = string
  default     = "crypto_signals_manager"
  description = "Nombre del repositorio (sin org)."
}

variable "github_branches" {
  type        = list(string)
  default     = ["main"]
  description = "Ramas que pueden asumir el rol de deploy (refs/heads/<branch>)."
}

variable "allow_pull_request" {
  type        = bool
  default     = true
  description = "Permite terraform plan desde workflows de pull_request."
}

variable "github_environments" {
  type        = list(string)
  default     = ["main"]
  description = "GitHub Environments (sub claim environment:<name>). Requerido si el workflow usa environment: main."
}

variable "role_name" {
  type    = string
  default = "crypto-trading-bot-github-actions-deploy"
}

variable "artifact_bucket" {
  type    = string
  default = "crypto-trading-bot-tfstate-913123310997"
}

variable "tf_state_bucket" {
  type    = string
  default = "crypto-trading-bot-tfstate-913123310997"
}

variable "tf_lock_table" {
  type    = string
  default = "crypto-trading-bot-tflock"
}
