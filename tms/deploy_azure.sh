#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DRY_RUN="${DRY_RUN:-0}"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/.env"
  set +a
fi

required_vars=(
  AZURE_RESOURCE_GROUP
  AZURE_LOCATION
  AZURE_PLAN_NAME
  AZURE_WEBAPP_NAME
  AZURE_ACR_NAME
  SECRET_KEY
  INTEGRATION_MASTER_KEY
  TMS_ADMIN_EMAIL
  TMS_DISPATCHER_EMAIL
  TMS_VIEWER_EMAIL
)

for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Missing required environment variable: ${var_name}" >&2
    exit 1
  fi
done

require_password_or_hash() {
  local password_var="$1"
  local hash_var="$2"
  if [[ -n "${!password_var:-}" || -n "${!hash_var:-}" ]]; then
    return 0
  fi
  echo "Missing required environment variable: ${password_var} or ${hash_var}" >&2
  exit 1
}

require_password_or_hash TMS_ADMIN_PASSWORD TMS_ADMIN_PASSWORD_HASH
require_password_or_hash TMS_DISPATCHER_PASSWORD TMS_DISPATCHER_PASSWORD_HASH
require_password_or_hash TMS_VIEWER_PASSWORD TMS_VIEWER_PASSWORD_HASH

if ! command -v az >/dev/null 2>&1; then
  echo "Azure CLI is required." >&2
  exit 1
fi

run_cmd() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

if [[ "${DRY_RUN}" != "1" ]]; then
  az account show >/dev/null
fi

IMAGE_NAME="${IMAGE_NAME:-tms-sandbox}"
IMAGE_TAG="${IMAGE_TAG:-$(date +%Y%m%d%H%M%S)}"
AZURE_PLAN_SKU="${AZURE_PLAN_SKU:-B1}"
TMS_DB_PATH="${TMS_DB_PATH:-/home/data/tms.db}"
TMS_CONTACTS_DB_PATH="${TMS_CONTACTS_DB_PATH:-/home/data/contacts.db}"
TMS_POD_UPLOAD_DIR="${TMS_POD_UPLOAD_DIR:-/home/data/uploads/pods}"
TMS_OTP_ISSUER="${TMS_OTP_ISSUER:-TMS Sandbox}"
TMS_ALLOWED_HOSTS="${TMS_ALLOWED_HOSTS:-${AZURE_WEBAPP_NAME}.azurewebsites.net}"
BASE_URL="${BASE_URL:-https://${AZURE_WEBAPP_NAME}.azurewebsites.net}"

echo "Ensuring resource group: ${AZURE_RESOURCE_GROUP}"
run_cmd az group create \
  --name "${AZURE_RESOURCE_GROUP}" \
  --location "${AZURE_LOCATION}" \
  --output none

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "Dry run: assuming Azure Container Registry exists or will be created."
elif ! az acr show --name "${AZURE_ACR_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" --output none 2>/dev/null; then
  echo "Creating Azure Container Registry: ${AZURE_ACR_NAME}"
  run_cmd az acr create \
    --name "${AZURE_ACR_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --sku Basic \
    --admin-enabled true \
    --location "${AZURE_LOCATION}" \
    --output none
fi

echo "Building container image in ACR"
run_cmd az acr build \
  --registry "${AZURE_ACR_NAME}" \
  --image "${IMAGE_NAME}:${IMAGE_TAG}" \
  --file "${SCRIPT_DIR}/Dockerfile" \
  "${REPO_ROOT}" \
  --output none

if [[ "${DRY_RUN}" == "1" ]]; then
  ACR_LOGIN_SERVER="${AZURE_ACR_NAME}.azurecr.io"
  ACR_USERNAME="<acr-username>"
  ACR_PASSWORD="<acr-password>"
else
  ACR_LOGIN_SERVER="$(az acr show --name "${AZURE_ACR_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" --query "loginServer" --output tsv)"
  ACR_USERNAME="$(az acr credential show --name "${AZURE_ACR_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" --query "username" --output tsv)"
  ACR_PASSWORD="$(az acr credential show --name "${AZURE_ACR_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" --query "passwords[0].value" --output tsv)"
fi
IMAGE_URI="${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "Dry run: assuming App Service plan exists or will be created."
elif ! az appservice plan show --name "${AZURE_PLAN_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" --output none 2>/dev/null; then
  echo "Creating App Service plan: ${AZURE_PLAN_NAME}"
  run_cmd az appservice plan create \
    --name "${AZURE_PLAN_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --is-linux \
    --sku "${AZURE_PLAN_SKU}" \
    --location "${AZURE_LOCATION}" \
    --output none
fi

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "Dry run: assuming Web App exists or will be created."
elif ! az webapp show --name "${AZURE_WEBAPP_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" --output none 2>/dev/null; then
  echo "Creating Linux web app: ${AZURE_WEBAPP_NAME}"
  run_cmd az webapp create \
    --name "${AZURE_WEBAPP_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --plan "${AZURE_PLAN_NAME}" \
    --container-image-name "${IMAGE_URI}" \
    --https-only true \
    --min-tls-version 1.2 \
    --output none
fi

echo "Updating container settings"
run_cmd az webapp config container set \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --container-image-name "${IMAGE_URI}" \
  --container-registry-url "https://${ACR_LOGIN_SERVER}" \
  --container-registry-user "${ACR_USERNAME}" \
  --container-registry-password "${ACR_PASSWORD}" \
  --enable-app-service-storage true \
  --output none

echo "Applying runtime settings"
run_cmd az webapp config appsettings set \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --settings \
    WEBSITES_PORT=8080 \
    TMS_ENV=production \
    TMS_APP_MODE=full \
    SESSION_COOKIE_SECURE=true \
    SECRET_KEY="${SECRET_KEY}" \
    INTEGRATION_MASTER_KEY="${INTEGRATION_MASTER_KEY}" \
    BASE_URL="${BASE_URL}" \
    TMS_DB_PATH="${TMS_DB_PATH}" \
    TMS_CONTACTS_DB_PATH="${TMS_CONTACTS_DB_PATH}" \
    TMS_POD_UPLOAD_DIR="${TMS_POD_UPLOAD_DIR}" \
    TMS_OTP_ISSUER="${TMS_OTP_ISSUER}" \
    TMS_ALLOWED_HOSTS="${TMS_ALLOWED_HOSTS}" \
    TMS_ENFORCE_CSRF=true \
    TMS_ENFORCE_ROUTE_AUTH=true \
    TMS_ALLOW_REQUEST_TENANT_OVERRIDE=false \
    TMS_ALLOW_REQUEST_ACTOR_OVERRIDE=false \
    TMS_ENABLE_NOTIFICATION_SCHEDULER=false \
    TMS_ENABLE_EDI_WATCHER=false \
    TMS_ADMIN_EMAIL="${TMS_ADMIN_EMAIL}" \
    TMS_ADMIN_PASSWORD="${TMS_ADMIN_PASSWORD:-}" \
    TMS_ADMIN_PASSWORD_HASH="${TMS_ADMIN_PASSWORD_HASH:-}" \
    TMS_ADMIN_NAME="${TMS_ADMIN_NAME:-Sandbox Admin}" \
    TMS_DISPATCHER_EMAIL="${TMS_DISPATCHER_EMAIL}" \
    TMS_DISPATCHER_PASSWORD="${TMS_DISPATCHER_PASSWORD:-}" \
    TMS_DISPATCHER_PASSWORD_HASH="${TMS_DISPATCHER_PASSWORD_HASH:-}" \
    TMS_DISPATCHER_NAME="${TMS_DISPATCHER_NAME:-Sandbox Dispatcher}" \
    TMS_VIEWER_EMAIL="${TMS_VIEWER_EMAIL}" \
    TMS_VIEWER_PASSWORD="${TMS_VIEWER_PASSWORD:-}" \
    TMS_VIEWER_PASSWORD_HASH="${TMS_VIEWER_PASSWORD_HASH:-}" \
    TMS_VIEWER_NAME="${TMS_VIEWER_NAME:-Sandbox Viewer}" \
    --output none

run_cmd az webapp config set \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --always-on true \
  --http20-enabled true \
  --min-tls-version 1.2 \
  --ftps-state Disabled \
  --output none

run_cmd az webapp update \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --https-only true \
  --output none

health_config_file="$(mktemp)"
trap 'rm -f "${health_config_file}"' EXIT
printf '{"healthCheckPath":"/health"}' > "${health_config_file}"

run_cmd az webapp config set \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --generic-configurations "@${health_config_file}" \
  --output none

echo "Deployment complete."
echo "Image: ${IMAGE_URI}"
echo "URL: https://${AZURE_WEBAPP_NAME}.azurewebsites.net"
