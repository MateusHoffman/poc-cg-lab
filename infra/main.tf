terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

variable "image" {
  type        = string
  description = "Imagem do backend publicada no ECR."
  default     = "cglab/autoagent:local"
}

variable "deployment_strategy" {
  type        = string
  description = "Estratégia de rollout do serviço. Canary e blue/green ficam no CodeDeploy em produção."
  default     = "canary"

  validation {
    condition     = contains(["rolling", "canary", "blue_green"], var.deployment_strategy)
    error_message = "deployment_strategy deve ser rolling, canary ou blue_green."
  }
}

resource "aws_dynamodb_table" "sessions" {
  name         = "CG_AutoAgent_Table"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }
}

resource "aws_s3_bucket" "assets" {
  bucket_prefix = "cglab-autoagent-"
}

resource "aws_cognito_user_pool" "buyers" {
  name = "cglab-autoagent-buyers"
}

resource "aws_ecs_cluster" "agents" {
  name = "cglab-agent-cluster"
}

resource "aws_ecs_task_definition" "api" {
  family                   = "cglab-autoagent"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.image
      essential = true
      portMappings = [
        { containerPort = 8080, protocol = "tcp" }
      ]
      environment = [
        { name = "DEPLOYMENT_STRATEGY", value = var.deployment_strategy }
      ]
    }
  ])
}
