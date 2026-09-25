output "resource_group_name" {
  description = "Resource group created for the ACA deployment."
  value       = azurerm_resource_group.main.name
}

output "container_app_name" {
  description = "The deployed Container App name."
  value       = azurerm_container_app.pyrit.name
}

output "container_app_url" {
  description = "HTTPS URL for the PyRIT Container App."
  value       = "https://${azurerm_container_app.pyrit.latest_revision_fqdn}"
}

output "acr_login_server" {
  description = "Azure Container Registry login server."
  value       = azurerm_container_registry.main.login_server
}
