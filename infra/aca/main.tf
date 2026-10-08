resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location
  tags     = var.common_tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "law-${replace(var.environment_name, "-", "")}-${random_string.suffix.result}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.common_tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_container_app_environment" "main" {
  name                       = var.environment_name
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = var.common_tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "azurerm_container_registry" "main" {
  count = var.container_registry_enabled ? 1 : 0

  name                = lower(replace(var.container_registry_name, "/[^a-z0-9]/", ""))
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = true
  tags                = var.common_tags

  lifecycle {
    prevent_destroy = true
  }
}

locals {
  pyrit_image = var.image_registry != "" ? "${var.image_registry}/${var.pyrit_image_name}:${var.image_tag}" : "${azurerm_container_registry.main[0].login_server}/${var.pyrit_image_name}:${var.image_tag}"
  frontend_image = var.image_registry != "" ? "${var.image_registry}/${var.frontend_image_name}:${var.image_tag}" : "${azurerm_container_registry.main[0].login_server}/${var.frontend_image_name}:${var.image_tag}"
  promptfoo_image = var.image_registry != "" ? "${var.image_registry}/${var.promptfoo_image_name}:${var.image_tag}" : "${azurerm_container_registry.main[0].login_server}/${var.promptfoo_image_name}:${var.image_tag}"
}

resource "azurerm_container_app" "main" {
  name                         = var.container_app_name
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  tags                         = var.common_tags

  lifecycle {
    prevent_destroy = true
  }

  identity {
    type = "SystemAssigned"
  }

  dynamic "secret" {
    for_each = (var.registry_password != "" || var.container_registry_enabled) ? [1] : []
    content {
      name  = "registry-password"
      value = var.registry_password != "" ? var.registry_password : azurerm_container_registry.main[0].admin_password
    }
  }

  ingress {
    external_enabled = true
    target_port      = 80
    transport        = "auto"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  registry {
    server              = var.registry_server != "" ? var.registry_server : azurerm_container_registry.main[0].login_server
    username            = var.registry_username != "" ? var.registry_username : azurerm_container_registry.main[0].admin_username
    password_secret_name = "registry-password"
  }

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name   = "frontend"
      image  = local.frontend_image
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "PORT"
        value = "80"
      }

      env {
        name  = "APP_ENV"
        value = var.app_env
      }

      env {
        name  = "BACKEND_API_URL"
        value = "http://localhost:8000"
      }
    }

    container {
      name   = "pyrit"
      image  = local.pyrit_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "PORT"
        value = "8000"
      }

      env {
        name  = "APP_ENV"
        value = var.app_env
      }

      env {
        name  = "BACKEND_API_URL"
        value = var.backend_api_url
      }

      env {
        name  = "BACKEND_API_TIMEOUT"
        value = tostring(var.backend_api_timeout)
      }

      env {
        name  = "AZURE_OPENAI_API_KEY"
        value = var.azure_openai_api_key
      }

      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = var.azure_openai_endpoint
      }

      env {
        name  = "AZURE_OPENAI_API_VERSION"
        value = var.azure_openai_api_version
      }

      env {
        name  = "AZURE_OPENAI_DEPLOYMENT"
        value = var.azure_openai_deployment
      }

      env {
        name  = "ADVERSARIAL_OPENAI_API_KEY"
        value = var.adversarial_openai_api_key
      }

      env {
        name  = "ADVERSARIAL_OPENAI_ENDPOINT"
        value = var.adversarial_openai_endpoint
      }

      env {
        name  = "ADVERSARIAL_OPENAI_DEPLOYMENT"
        value = var.adversarial_openai_deployment
      }

      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      env {
        name  = "AZURE_STORAGE_CONNECTION_STRING"
        value = var.azure_storage_connection_string
      }

      env {
        name  = "AZURE_STORAGE_CONTAINER_NAME"
        value = var.azure_storage_container_name
      }
    }

    container {
      name   = "promptfoo"
      image  = local.promptfoo_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "PORT"
        value = "8001"
      }

      env {
        name  = "APP_ENV"
        value = var.app_env
      }

      env {
        name  = "BACKEND_API_URL"
        value = "http://localhost:8000"
      }

      env {
        name  = "PROMPTFOO_RUN_TOKEN"
        value = var.promptfoo_run_token
      }

      env {
        name  = "AZURE_OPENAI_API_KEY"
        value = var.azure_openai_api_key
      }

      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = var.azure_openai_endpoint
      }

      env {
        name  = "AZURE_OPENAI_API_VERSION"
        value = var.azure_openai_api_version
      }

      env {
        name  = "AZURE_OPENAI_DEPLOYMENT"
        value = var.azure_openai_deployment
      }

      env {
        name  = "ADVERSARIAL_OPENAI_API_KEY"
        value = var.adversarial_openai_api_key
      }

      env {
        name  = "ADVERSARIAL_OPENAI_ENDPOINT"
        value = var.adversarial_openai_endpoint
      }

      env {
        name  = "ADVERSARIAL_OPENAI_DEPLOYMENT"
        value = var.adversarial_openai_deployment
      }
    }
  }
}
