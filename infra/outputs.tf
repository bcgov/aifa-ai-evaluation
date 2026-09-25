output "resource_group_name" {
  description = "Resource group created for this app."
  value       = azurerm_resource_group.main.name
}

output "app_service_name" {
  description = "Name of the Azure App Service instance."
  value       = azurerm_linux_web_app.main.name
}

output "app_service_url" {
  description = "Primary HTTPS endpoint for the app."
  value       = "https://${azurerm_linux_web_app.main.default_hostname}"
}

output "app_service_plan_name" {
  description = "App Service plan name."
  value       = azurerm_service_plan.main.name
}
