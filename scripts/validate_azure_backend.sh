#!/usr/bin/env bash
set -euo pipefail

missing=()
check(){ var=$1; if [ -z "${!var:-}" ]; then missing+=("$var"); fi }
# variables used by Terraform backend and provider
vars=(ARM_SUBSCRIPTION_ID ARM_TENANT_ID ARM_CLIENT_ID TF_STATE_RESOURCE_GROUP TF_STATE_STORAGE_ACCOUNT_NAME TF_STATE_CONTAINER_NAME TF_STATE_KEY TF_STATE_ACCESS_KEY ARM_USE_OIDC)
for v in "${vars[@]}"; do check $v; done

if [ ${#missing[@]} -ne 0 ]; then
  echo "Missing required environment variables:" >&2
  for m in "${missing[@]}"; do echo " - $m" >&2; done
  exit 2
fi

echo "All required backend/provider environment variables are present."

echo "Checking Terraform init (dry-run) in infra/aca..."
( cd infra/aca && terraform init -backend-config="resource_group_name=${TF_STATE_RESOURCE_GROUP}" -backend-config="storage_account_name=${TF_STATE_STORAGE_ACCOUNT_NAME}" -backend-config="container_name=${TF_STATE_CONTAINER_NAME}" -backend-config="key=${TF_STATE_KEY}" -backend-config="access_key=${TF_STATE_ACCESS_KEY}" -reconfigure )

echo "Terraform init completed (backend configured)."