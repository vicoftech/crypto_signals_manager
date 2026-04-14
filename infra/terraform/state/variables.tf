variable "aws_region" {
  description = "AWS region for terraform state resources"
  type        = string
  default     = "ap-northeast-1"
}

variable "aws_profile" {
  description = "AWS shared profile name"
  type        = string
  default     = "asap_main"
}
