#!/usr/bin/env bash
# One-time Azure setup for TripGenie. Run it as the subscription owner after
# `az login`; it is safe to re-run. It creates what main.bicep and the
# GitHub workflow assume already exists:
#
#   - the resource group
#   - a container registry, and an identity the apps use to pull from it
#   - a managed identity GitHub Actions signs in as through OIDC (no client
#     secret), trusted for `main` and the `production` environment, and allowed
#     to deploy only inside the resource group
#
# A managed identity rather than an Entra app registration: university tenants
# (UTS included) stop students registering apps, but a subscription owner can
# always create identities. Owner rights are needed once, for the role
# assignments; everything after this runs as that identity with Contributor on
# the resource group only.
set -euo pipefail

repo=${GITHUB_REPOSITORY:-JulianKirk/TripGenie}
rg=${AZURE_RESOURCE_GROUP:-rg-tripgenie}
location=${AZURE_LOCATION:-australiaeast}

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

github=$(az identity create --name tripgenie-github --resource-group "$rg" \
  --query '{client: clientId, principal: principalId}' -o tsv)
read -r client_id github_principal <<< "$github"

for subject in ref:refs/heads/main environment:production; do
  az identity federated-credential create --name "github-$(echo "$subject" | tr ':/' '--')" \
    --identity-name tripgenie-github --resource-group "$rg" \
    --issuer https://token.actions.githubusercontent.com \
    --subject "repo:$repo:$subject" --audiences api://AzureADTokenExchange -o none
done

for attempt in 1 2 3 4 5; do
  az role assignment create --assignee-object-id "$github_principal" \
    --assignee-principal-type ServicePrincipal --role Contributor \
    --scope "$rg_id" -o none && break
  sleep 10
done

cat <<EOF

Azure is ready. Set these as GitHub Actions repository variables (Settings ->
Secrets and variables -> Actions -> Variables). None of them is a secret.

  AZURE_CLIENT_ID=$client_id
  AZURE_TENANT_ID=$tenant
  AZURE_SUBSCRIPTION_ID=$subscription
  AZURE_RESOURCE_GROUP=$rg

or, as a repository admin:

  gh variable set AZURE_CLIENT_ID -R $repo -b $client_id
  gh variable set AZURE_TENANT_ID -R $repo -b $tenant
  gh variable set AZURE_SUBSCRIPTION_ID -R $repo -b $subscription
  gh variable set AZURE_RESOURCE_GROUP -R $repo -b $rg

Then create the GitHub environment "production" with a required reviewer: that
approval is the human release decision for each cloud deployment.
EOF
