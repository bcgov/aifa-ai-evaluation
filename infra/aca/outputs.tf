output "resource_group_name" {
  description = "Resource group created for the ACA deployment."
  value       = azurerm_resource_group.main.name
}

output "container_app_name" {
  description = "The deployed multi-container Container App name."
  value       = azurerm_container_app.main.name
}

output "container_app_url" {
  description = "HTTPS URL for the public frontend entry point on the unified Container App."
  value       = "https://${azurerm_container_app.main.latest_revision_fqdn}"
}

output "pyrit_image_reference" {
  description = "Resolved image reference for the PyRIT container."
  value       = local.pyrit_image
}

output "frontend_image_reference" {
  description = "Resolved image reference for the frontend container."
  value       = local.frontend_image
}

output "promptfoo_image_reference" {
  description = "Resolved image reference for the Promptfoo container."
  value       = local.promptfoo_image
}

output "acr_login_server" {
  description = "Azure Container Registry login server when one is provisioned; otherwise empty."
  value       = var.container_registry_enabled ? azurerm_container_registry.main[0].login_server : ""
}
