#!/usr/bin/env bash
# One-time Azure setup for TripGenie. Run it as the subscription owner after
# `az login`; it is safe to re-run. It creates what main.bicep and the
# GitHub workflow assume already exists:
#
#   - the resource group
#   - a container registry, and an identity the apps use to pull from it
#   - an Entra app GitHub Actions signs in as through OIDC (no client secret),
#     trusted for `main` and the `production` environment, and allowed to
#     deploy only inside the resource group
#
# Owner rights are needed once, for the role assignments; everything after this
# runs as the GitHub app with Contributor on the resource group only.
set -euo pipefail

repo=${GITHUB_REPOSITORY:-JulianKirk/TripGenie}
rg=${AZURE_RESOURCE_GROUP:-rg-tripgenie}
location=${AZURE_LOCATION:-australiaeast}
github_app=tripgenie-github-deploy

subscription=$(az account show --query id -o tsv)
tenant=$(az account show --query tenantId -o tsv)
# Registry names are global and alphanumeric only.
registry=tripgenie${subscription:0:8}

for provider in Microsoft.App Microsoft.OperationalInsights Microsoft.Storage \
  Microsoft.ContainerRegistry Microsoft.ManagedIdentity; do
  az provider register --namespace "$provider" --wait
done

rg_id=$(az group create --name "$rg" --location "$location" --query id -o tsv)

registry_id=$(az acr show --name "$registry" --query id -o tsv 2>/dev/null) ||
  registry_id=$(az acr create --name "$registry" --resource-group "$rg" \
    --sku Basic --admin-enabled false --query id -o tsv)

pull_principal=$(az identity create --name tripgenie-pull --resource-group "$rg" \
  --query principalId -o tsv)
# A fresh identity can take a moment to reach Entra; the assignment retries.
for attempt in 1 2 3 4 5; do
  az role assignment create --assignee-object-id "$pull_principal" \
    --assignee-principal-type ServicePrincipal --role AcrPull \
    --scope "$registry_id" -o none && break
  sleep 10
done

app_id=$(az ad app list --display-name "$github_app" --query '[0].appId' -o tsv)
[ -n "$app_id" ] ||
  app_id=$(az ad app create --display-name "$github_app" --query appId -o tsv)
az ad sp show --id "$app_id" -o none 2>/dev/null || az ad sp create --id "$app_id" -o none

for subject in ref:refs/heads/main environment:production; do
  name=github-$(echo "$subject" | tr ':/' '--')
  if [ -z "$(az ad app federated-credential list --id "$app_id" --query "[?name=='$name'].name" -o tsv)" ]; then
    az ad app federated-credential create --id "$app_id" -o none --parameters "{
      \"name\": \"$name\",
      \"issuer\": \"https://token.actions.githubusercontent.com\",
      \"subject\": \"repo:$repo:$subject\",
      \"audiences\": [\"api://AzureADTokenExchange\"]
    }"
  fi
done

for attempt in 1 2 3 4 5; do
  az role assignment create --assignee "$app_id" --role Contributor --scope "$rg_id" -o none && break
  sleep 10
done

cat <<EOF

Azure is ready. Set these as GitHub Actions repository variables (Settings ->
Secrets and variables -> Actions -> Variables). None of them is a secret.

  AZURE_CLIENT_ID=$app_id
  AZURE_TENANT_ID=$tenant
  AZURE_SUBSCRIPTION_ID=$subscription
  AZURE_RESOURCE_GROUP=$rg

or, as a repository admin:

  gh variable set AZURE_CLIENT_ID -R $repo -b $app_id
  gh variable set AZURE_TENANT_ID -R $repo -b $tenant
  gh variable set AZURE_SUBSCRIPTION_ID -R $repo -b $subscription
  gh variable set AZURE_RESOURCE_GROUP -R $repo -b $rg

Then create the GitHub environment "production" with a required reviewer: that
approval is the human release decision for each cloud deployment.
EOF
