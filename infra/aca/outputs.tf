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
  description = "Azure Container Registry login server when one is provisioned; otherwise empty."
  value       = var.container_registry_enabled ? azurerm_container_registry.main[0].login_server : ""
}

output "image_reference" {
  description = "Resolved image reference for the deployed Container App."
  value       = var.image_registry != "" ? "${var.image_registry}/${var.image_name}:${var.image_tag}" : (var.container_registry_enabled ? "${azurerm_container_registry.main[0].login_server}/${var.image_name}:${var.image_tag}" : "")
}
