variable "subscription_id" {
  description = "Azure subscription ID used for the ACA deployment."
  type        = string
  default     = ""
}

variable "tenant_id" {
  description = "Azure tenant ID used for OIDC auth."
  type        = string
  default     = ""
}

variable "client_id" {
  description = "Azure client ID used by OIDC login. Leave blank for Azure CLI auth."
  type        = string
  default     = ""
}

variable "use_oidc" {
  description = "Use OIDC in GitHub Actions when authenticating to Azure."
  type        = bool
  default     = true
}

variable "location" {
  description = "Azure region for the resource group and Container Apps environment."
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Resource group for the PyRIT ACA deployment."
  type        = string
  default     = "nr-ai-form-dev"
}

variable "environment_name" {
  description = "Container Apps environment name."
  type        = string
  default     = "nraif-671b-dev-dev-containerenv"
}

variable "container_app_name" {
  description = "Legacy frontend Container App name kept for compatibility. New deployments should use frontend_container_app_name."
  type        = string
  default     = "ca-aifa-pyrit-dev"
}

variable "frontend_container_app_name" {
  description = "Public frontend Container App name."
  type        = string
  default     = "ca-aifa-frontend-dev"
}

variable "pyrit_container_app_name" {
  description = "Private PyRIT Container App name."
  type        = string
  default     = "ca-aifa-pyrit-private-dev"
}

variable "promptfoo_container_app_name" {
  description = "Private Promptfoo Container App name."
  type        = string
  default     = "ca-aifa-promptfoo-private-dev"
}

variable "container_registry_enabled" {
  description = "Whether to provision and use an Azure Container Registry for the Container App. Set false when using external registries such as GHCR."
  type        = bool
  default     = true
}

variable "container_registry_name" {
  description = "Azure Container Registry name, must be globally unique."
  type        = string
  default     = "aifaevaldevacr"
}

variable "image_registry" {
  description = "Image registry host, for example ghcr.io. If blank, defaults to the Azure Container Registry login server."
  type        = string
  default     = ""
}

variable "pyrit_image_name" {
  description = "Image repository name for the PyRIT service, such as bcgov/aifa-ai-evaluation-pyrit."
  type        = string
  default     = "aifa-ai-evaluation-pyrit"
}

variable "frontend_image_name" {
  description = "Image repository name for the frontend service."
  type        = string
  default     = "aifa-ai-evaluation-frontend"
}

variable "promptfoo_image_name" {
  description = "Image repository name for the Promptfoo service."
  type        = string
  default     = "aifa-ai-evaluation-promptfoo"
}

variable "image_tag" {
  description = "Shared image tag for the multi-container service set."
  type        = string
  default     = "latest"
}

variable "registry_server" {
  description = "External registry server to use when container_registry_enabled is false. Example: ghcr.io"
  type        = string
  default     = ""
}

variable "registry_username" {
  description = "Username for the external registry connection."
  type        = string
  default     = ""
}

variable "registry_password" {
  description = "Password/token used to authenticate to the external registry."
  type        = string
  default     = ""
  sensitive   = true
}

variable "app_env" {
  description = "Environment label used by the app."
  type        = string
  default     = "dev"
}

variable "backend_api_url" {
  description = "Hosted AI Form Assist backend endpoint used by the evaluation app."
  type        = string
  default     = "http://localhost:8000"
}

variable "pyrit_backend_api_url" {
  description = "Public or private URL for the PyRIT backend app accessible by the frontend."
  type        = string
  default     = "https://ca-aifa-pyrit-private-dev.<replace-with-environment-domain>/api"
}

variable "promptfoo_backend_api_url" {
  description = "Public or private URL for the Promptfoo app accessible by the frontend."
  type        = string
  default     = "https://ca-aifa-promptfoo-private-dev.<replace-with-environment-domain>/api"
}

variable "promptfoo_run_token" {
  description = "Optional token required to invoke the Promptfoo runner endpoint."
  type        = string
  default     = ""
  sensitive   = true
}

variable "backend_api_timeout" {
  description = "Timeout in seconds used for backend requests."
  type        = number
  default     = 30
}

variable "azure_openai_api_key" {
  description = "Azure OpenAI API key."
  type        = string
  default     = ""
  sensitive   = true
}

variable "azure_openai_endpoint" {
  description = "Azure OpenAI resource root URL."
  type        = string
  default     = ""
}

variable "azure_openai_api_version" {
  description = "Azure OpenAI API version."
  type        = string
  default     = "2025-01-01-preview"
}

variable "azure_openai_deployment" {
  description = "Deployment name for the main Azure OpenAI model."
  type        = string
  default     = "gpt-4"
}

variable "adversarial_openai_api_key" {
  description = "API key for the adversarial Azure OpenAI endpoint."
  type        = string
  default     = ""
  sensitive   = true
}

variable "adversarial_openai_endpoint" {
  description = "Endpoint for adversarial prompting."
  type        = string
  default     = ""
}

variable "adversarial_openai_deployment" {
  description = "Deployment name for the adversarial model."
  type        = string
  default     = "gpt-4"
}

variable "azure_storage_connection_string" {
  description = "Optional Azure Blob Storage connection string for report persistence. Leave empty to use local results files."
  type        = string
  default     = ""
  sensitive   = true
}

variable "azure_storage_container_name" {
  description = "Optional blob container name for Azure reports storage."
  type        = string
  default     = "aifa-reports"
}

variable "common_tags" {
  description = "Resource tags for ACA deployment."
  type        = map(string)
  default = {
    application = "aifa-ai-evaluation"
    workload    = "pyrit"
    managed_by  = "terraform"
    environment = "dev"
  }
}
