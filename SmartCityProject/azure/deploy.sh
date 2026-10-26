#!/bin/bash
# Deploys the app to Azure App Service (Linux, Python). Requires: Azure CLI (az login done).
# UNVERIFIED in the project's test environment (no Azure subscription was available).
# Usage: ./azure/deploy.sh <unique-app-name> [resource-group] [location]
set -euo pipefail
APP="${1:?Usage: deploy.sh <unique-app-name> [resource-group] [location]}"
RG="${2:-smartcity-rg}"
LOC="${3:-centralindia}"
SKU="${SKU:-B1}"     # B1 supports Always On; F1 (free) sleeps when idle, which pauses the simulator

az group create --name "$RG" --location "$LOC"
az appservice plan create --name "$APP-plan" --resource-group "$RG" --sku "$SKU" --is-linux
az webapp create --name "$APP" --resource-group "$RG" --plan "$APP-plan" --runtime "PYTHON:3.12"
az webapp config appsettings set --name "$APP" --resource-group "$RG" --settings \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true SMARTCITY_DATA_DIR=/home/data SQLITE_JOURNAL_MODE=DELETE \
  SIMULATOR_ENABLED=1 SIM_INTERVAL_SECONDS=5
az webapp config set --name "$APP" --resource-group "$RG" --startup-file "startup.sh" \
  $( [ "$SKU" != "F1" ] && echo "--always-on true" )
rm -f /tmp/smartcity.zip
zip -qr /tmp/smartcity.zip . -x "data/*" "*__pycache__*" ".git/*" ".venv/*" "tests/*"
az webapp deploy --name "$APP" --resource-group "$RG" --src-path /tmp/smartcity.zip --type zip
echo "Open: https://$APP.azurewebsites.net   Health: https://$APP.azurewebsites.net/api/health"
