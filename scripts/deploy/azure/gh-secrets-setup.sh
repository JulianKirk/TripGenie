#!/bin/bash
set -e

# One-time, local-only (Lab 11's gh-secrets-setup.sh, adapted):
# - creates the identity GitHub Actions signs in as through OIDC (if missing)
# - pushes its identifiers to GitHub Actions secrets.
#
# Lab 11 creates an Entra app registration. The UTS tenant blocks students from
# registering apps (allowedToCreateApps=false), so this uses a user-assigned
# managed identity instead: it takes federated credentials the same way and only
# needs subscription Owner, which Azure for Students grants. It lives in its own
# resource group so cleanup.sh never deletes CI's sign-in.

# Prevents Git Bash on Windows from rewriting --scope "/subscriptions/..." into a local file path.
export MSYS_NO_PATHCONV=1

IDENTITY_GROUP="${IDENTITY_GROUP:-rg-tripgenie-github}"
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-tripgenie}"
IDENTITY_NAME="tripgenie-github-oidc"
LOCATION="${LOCATION:-australiaeast}"

echo "=== TripGenie GitHub Secrets Setup ==="

az account show >/dev/null 2>&1 || az login
echo "Logged in to Azure."

if ! gh auth status >/dev/null 2>&1; then
    gh auth login
    echo "Logged in to GitHub."
fi

REPO_URL=$(git config --get remote.origin.url)
REPO_SLUG=$(echo "$REPO_URL" | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')

# The remote may still use a name the repo had before a rename or transfer;
# GitHub redirects it, so ask for the repo's current name.
if ! REPO=$(gh api "repos/${REPO_SLUG}" --jq '.full_name') || [ -z "$REPO" ]; then
    echo "Could not look up GitHub repository '${REPO_SLUG}'." >&2
    exit 1
fi
[ "$REPO" = "$REPO_SLUG" ] || echo "Remote '${REPO_SLUG}' is now '${REPO}'; using '${REPO}'."

# The OIDC subject is whatever GitHub issues, so ask GitHub rather than build it
# from names: an immutable subject (repos created after 2026-07-15, TripGenie
# included) carries owner and repo IDs as well, and either kind changes when the
# repo is renamed or transferred. Only the default template is supported: a
# custom one (include_claim_keys) puts other claims in front of the environment.
if ! OIDC=$(gh api "repos/${REPO}/actions/oidc/customization/sub" \
    --jq '"\(.use_default)\t\(.sub_claim_prefix // "")"'); then
    echo "Could not read the OIDC subject template of '${REPO}'." >&2
    exit 1
fi
IFS=$'\t' read -r USE_DEFAULT REPO_SUBJECT <<< "$OIDC"
if [ "$USE_DEFAULT" != "true" ]; then
    echo "'${REPO}' uses a custom OIDC subject template; this script supports only the default one." >&2
    exit 1
fi
if [[ "$REPO_SUBJECT" != repo:* ]]; then
    echo "GitHub reported no OIDC subject prefix for '${REPO}'; not guessing one." >&2
    exit 1
fi
echo "GitHub OIDC subject prefix: '${REPO_SUBJECT}'."

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)

if [ -z "$SUBSCRIPTION_ID" ]; then
    echo "No active subscription found on the current Azure login."
    echo "Run 'az account list --output table' to see available subscriptions, then 'az account set --subscription <id>' and re-run this script."
    exit 1
fi

# Lab 11 lets CI register these; CI's identity here can only act inside the
# deployment resource group, so the subscription owner registers them once.
for PROVIDER in Microsoft.App Microsoft.OperationalInsights Microsoft.ContainerRegistry; do
    az provider register --namespace "$PROVIDER" --wait
done

az group create --name "$IDENTITY_GROUP" --location "$LOCATION" -o none
# Only when missing: `az group create` on an existing group wipes its tags,
# which hold env-setup.sh's deployment names.
if [ "$(az group exists --name "$RESOURCE_GROUP")" != "true" ]; then
    az group create --name "$RESOURCE_GROUP" --location "$LOCATION" -o none
fi
RG_SCOPE=$(az group show --name "$RESOURCE_GROUP" --query id -o tsv)
CLIENT_ID=$(az identity create --name "$IDENTITY_NAME" --resource-group "$IDENTITY_GROUP" --query clientId -o tsv)
PRINCIPAL_ID=$(az identity show --name "$IDENTITY_NAME" --resource-group "$IDENTITY_GROUP" --query principalId -o tsv)
echo "Fetched subscription ID, tenant ID, and client ID from Azure."

# Re-synced on every run (not just at creation): the subject changes if the repo
# is renamed or transferred.
# Only the `production` environment is trusted: the deploy job runs in it, so a
# token is issued only after its required reviewer approves. Trusting a branch
# too would let any job on it sign in without that approval.
for SUFFIX in environment:production; do
    FED_CRED_NAME="github-$(echo "$SUFFIX" | tr ':/' '--')"
    az identity federated-credential create \
      --name "$FED_CRED_NAME" \
      --identity-name "$IDENTITY_NAME" \
      --resource-group "$IDENTITY_GROUP" \
      --issuer https://token.actions.githubusercontent.com \
      --subject "${REPO_SUBJECT}:${SUFFIX}" \
      --audiences api://AzureADTokenExchange -o none
    echo "Synced federated credential to subject '${REPO_SUBJECT}:${SUFFIX}'."
done

# Checked on every run: an earlier run may have created the identity but failed
# before granting roles. Lab 11 grants these on the whole subscription; here they
# cover only the deployment resource group, so CI cannot touch anything else.
# User Access Administrator: Contributor alone excludes roleAssignments/write,
# which build-images.sh needs to grant the apps' registry identity AcrPull.
for ROLE in "Contributor" "User Access Administrator"; do
    EXISTING=$(az role assignment list --assignee "$PRINCIPAL_ID" --role "$ROLE" --scope "$RG_SCOPE" --query "[0].id" -o tsv 2>/dev/null || true)
    if [ -n "$EXISTING" ]; then
        echo "$ROLE role already assigned."
        continue
    fi
    # A fresh identity can take a moment to reach Entra.
    GRANTED=""
    for attempt in 1 2 3 4 5; do
        if az role assignment create \
          --assignee-object-id "$PRINCIPAL_ID" \
          --assignee-principal-type ServicePrincipal \
          --role "$ROLE" \
          --scope "$RG_SCOPE" -o none; then
            GRANTED=1
            break
        fi
        sleep 10
    done
    if [ -z "$GRANTED" ]; then
        echo "Could not grant $ROLE on $RESOURCE_GROUP. Are you the subscription Owner?" >&2
        exit 1
    fi
    echo "Granted $ROLE role on $RESOURCE_GROUP."
done

gh secret set AZURE_SUBSCRIPTION_ID --repo "$REPO" --body "$SUBSCRIPTION_ID"
gh secret set AZURE_TENANT_ID --repo "$REPO" --body "$TENANT_ID"
gh secret set AZURE_CLIENT_ID --repo "$REPO" --body "$CLIENT_ID"
echo "Pushed AZURE_SUBSCRIPTION_ID, AZURE_TENANT_ID, and AZURE_CLIENT_ID to GitHub Actions secrets."

echo "=== GitHub Secrets Setup Complete ==="
