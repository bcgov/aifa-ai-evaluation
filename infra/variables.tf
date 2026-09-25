variable "subscription_id" {
  description = "Azure subscription id for the deployment."
  type        = string
  default     = ""
}

variable "tenant_id" {
  description = "Azure tenant id for the deployment."
  type        = string
  default     = ""
}

variable "client_id" {
  description = "Azure client id used by OIDC login. Leave empty for service principal or Azure CLI auth."
  type        = string
  default     = ""
}

variable "use_oidc" {
  description = "Use OIDC for Azure login in GitHub Actions."
  type        = bool
  default     = true
}

variable "location" {
  description = "Azure region for the App Service resources."
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Resource group that holds the App Service."
  type        = string
  default     = "rg-aifa-ai-evaluation-dev"
}

variable "app_name" {
  description = "App Service name that is globally unique."
  type        = string
  default     = "aifa-ai-evaluation-dev"
}

variable "app_env" {
  description = "Environment label used in config and naming."
  type        = string
  default     = "dev"
}

variable "app_service_plan_name" {
  description = "Name of the Azure App Service plan."
  type        = string
  default     = "asp-aifa-ai-evaluation-dev"
}

variable "app_service_sku_name" {
  description = "App Service Plan SKU. Start with B1 and adjust after validation."
  type        = string
  default     = "B1"
}

variable "python_version" {
  description = "Python runtime version for the App Service."
  type        = string
  default     = "3.11"
}

variable "backend_api_url" {
  description = "URL of the hosted AI Form Assist backend that the evaluation app calls."
  type        = string
  default     = "http://localhost:8000"
}

variable "backend_api_timeout" {
  description = "Timeout in seconds for backend API requests."
  type        = number
  default     = 30
}

variable "azure_openai_api_key" {
  description = "Azure OpenAI API key used by the evaluation app."
  type        = string
  default     = ""
  sensitive   = true
}

variable "azure_openai_endpoint" {
  description = "Azure OpenAI endpoint root URL."
  type        = string
  default     = ""
}

variable "azure_openai_api_version" {
  description = "Azure OpenAI API version."
  type        = string
  default     = "2025-01-01-preview"
}

variable "azure_openai_deployment" {
  description = "Deployment name used by the main Azure OpenAI chat model."
  type        = string
  default     = "gpt-4"
}

variable "adversarial_openai_endpoint" {
  description = "Endpoint used for attack generation and adversarial prompting."
  type        = string
  default     = ""
}

variable "adversarial_openai_api_key" {
  description = "Key used for the adversarial Azure OpenAI endpoint."
  type        = string
  default     = ""
  sensitive   = true
}

variable "adversarial_openai_deployment" {
  description = "Deployment name used by the adversarial model."
  type        = string
  default     = "gpt-4"
}

variable "app_settings" {
  description = "Additional app settings to merge into the web app configuration."
  type        = map(string)
  default     = {}
}

variable "common_tags" {
  description = "Resource tags applied across the deployment."
  type        = map(string)
  default = {
    application = "aifa-ai-evaluation"
    managed_by  = "terraform"
    environment = "dev"
  }
}
