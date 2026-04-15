terraform {
  required_version = ">= 1.5.0"

  backend "s3" {
    bucket         = "crypto-trading-bot-tfstate-913123310997"
    key            = "audit/terraform.tfstate"
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
