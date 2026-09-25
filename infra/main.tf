resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location
  tags     = var.common_tags
}

resource "azurerm_service_plan" "main" {
  name                = var.app_service_plan_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  os_type             = "Linux"
  sku_name            = var.app_service_sku_name
  tags                = var.common_tags
}

resource "azurerm_linux_web_app" "main" {
  name                = var.app_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  service_plan_id     = azurerm_service_plan.main.id
  https_only          = true
  tags                = var.common_tags

  identity {
    type = "SystemAssigned"
  }

  app_settings = merge(
    {
      "WEBSITES_PORT"                           = "8000"
      "SCM_DO_BUILD_DURING_DEPLOYMENT"          = "true"
      "ENABLE_ORYX_BUILD"                       = "true"
      "PYTHONPATH"                              = "/home/site/wwwroot"
      "BACKEND_API_URL"                          = var.backend_api_url
      "BACKEND_API_TIMEOUT"                      = tostring(var.backend_api_timeout)
      "AZURE_OPENAI_API_KEY"                     = var.azure_openai_api_key
      "AZURE_OPENAI_ENDPOINT"                   = var.azure_openai_endpoint
      "AZURE_OPENAI_API_VERSION"                 = var.azure_openai_api_version
      "AZURE_OPENAI_DEPLOYMENT"                  = var.azure_openai_deployment
      "ADVERSARIAL_OPENAI_API_KEY"               = var.adversarial_openai_api_key
      "ADVERSARIAL_OPENAI_ENDPOINT"             = var.adversarial_openai_endpoint
      "ADVERSARIAL_OPENAI_DEPLOYMENT"            = var.adversarial_openai_deployment
      "EVALUATION_RUN_NAME"                      = "aifa_app_service_run"
      "EVALUATION_SCENARIO"                      = "water_permitting"
      "LOG_LEVEL"                                = "INFO"
      "APP_ENV"                                  = var.app_env
      "WEBSITE_RUN_FROM_PACKAGE"                 = "1"
      "PYTHONDONTWRITEBYTECODE"                  = "1"
      "PYTHONUNBUFFERED"                         = "1"
      "WEBSITE_HEALTHCHECK_MAXPINGFAILURES"      = "10"
      "WEBSITE_ENABLE_SYNC_UPDATE_SITE"          = "true"
    },
    var.app_settings
  )

  site_config {
    always_on                 = true
    ftps_state                = "FtpsOnly"
    health_check_path         = "/api/health"
    http2_enabled             = true
    minimum_tls_version       = "1.2"
    container_registry_use_managed_identity = false
    application_stack {
      python_version = var.python_version
    }

    app_command_line = "gunicorn --bind=0.0.0.0:$PORT --timeout 120 --workers 2 aifa_pyrit.web_app:app"
  }
}
