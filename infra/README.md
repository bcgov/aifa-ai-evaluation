# Infrastructure and release

Terraform in [aca/](aca) deploys one **Azure Container App** with three containers (`frontend` nginx with the only public ingress, `pyrit`, `promptfoo`) into a Container App Environment with Log Analytics. Images come from GHCR. The pipeline is [../.github/workflows/deploy-pyrit-aca.yml](../.github/workflows/deploy-pyrit-aca.yml).

The Terraform files directly in `infra/` are an earlier App Service stack that the pipeline no longer uses.

## First-time setup

```bash
az login && gh auth login
../initial-azure-setup.sh -g <resource-group> -n <identity-name> -r <org>/<repo> -e dev \
  --create-storage --create-github-secrets
```

This creates a managed identity with GitHub OIDC (no stored credentials) and the Terraform state storage. Then add the identity to the Azure contributor security group (see the header of the script). Set these in the GitHub `dev` environment:

| Kind | Names |
|---|---|
| Secrets | `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `TF_STATE_STORAGE_ACCOUNT_NAME`, `AUDIT_LLM_API_KEY`, `ADVERSARIAL_OPENAI_API_KEY`, `AZURE_STORAGE_CONNECTION_STRING`, `PROMPTFOO_RUN_TOKEN` |
| Variables | `BACKEND_API_URL`, `AUDIT_LLM_ENDPOINT`, `AUDIT_LLM_DEPLOYMENT`, `ADVERSARIAL_OPENAI_ENDPOINT`, `ADVERSARIAL_OPENAI_DEPLOYMENT`, and optionally `AZURE_LOCATION`, `ACA_RESOURCE_GROUP`, `ACA_ENVIRONMENT_NAME`, `ACA_CONTAINER_APP_NAME`, `APP_ENV`, and the four Blob container names (`PYRIT_*`, `PROMPTFOO_*`) |

Container-level variables are listed in [../env-inventory.md](../env-inventory.md). Check Terraform backend variables locally with `../scripts/validate_azure_backend.sh`.

## Release

1. Push or open a PR: images `aifa-ai-evaluation-{pyrit,frontend,promptfoo}` are built and pushed to GHCR (`latest`, `sha-<commit>`, `run-<n>`), then `terraform plan` runs.
2. Actions → **Deploy to ACA** → Run workflow → `plan`, review the output, then run again with `apply`.
3. Read the `container_app_url` output and check `/healthz`, `/api/health`, `/api/promptfoo/info`.

**Rollback:** re-run the `apply` run of the last good release; it deploys that run's image tag.

## Run Terraform by hand

```bash
cd infra/aca
terraform init      # backend settings come from the pipeline's TF_STATE_* values
terraform plan -var-file=<your>.tfvars
```

Key variables ([aca/variables.tf](aca/variables.tf)): `resource_group_name`, `environment_name`, `container_app_name`, `image_registry`, `image_tag`, `backend_api_url`, the `AUDIT_LLM_*` and `adversarial_openai_*` settings, `azure_storage_connection_string`, `promptfoo_run_token`. Outputs: `container_app_url`, image references.

## Notes

- Container sizes: frontend 0.25 vCPU, pyrit 0.5, promptfoo 1.0.
- Registry options (ACR or GHCR): [../docs/REGISTRY.md](../docs/REGISTRY.md).
- Never put secrets in `.tfvars` files that are committed.
