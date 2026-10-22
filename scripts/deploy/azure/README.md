# Azure cloud deployment

TripGenie's cloud baseline runs on **Azure Container Apps**. It follows the
deployment scripts and CI/CD workflow of
[ASD Lab 11](https://github.com/Georges034302/asd-labs/blob/main/Lab_11_Testing_Deployment_and_Operations.md).
Frontends, backends and databases are deployed. AI-Mode, MCP, RAG and the
Multi-Agent Server stay local-only and are disabled in the cloud
(`shared/configuration/.env.cloud`).

```
GitHub Actions ──OIDC──> Azure
  cloud-deployment.yml     rg-tripgenie-github   tripgenie-github-oidc identity (kept by cleanup)
                           rg-tripgenie
                             ├─ Container Registry (tripgenie-* images)
                             └─ Container Apps environment
                                  ├─ shared-ui, student-N-frontend   public HTTPS
                                  └─ *-backend, *-database           internal TCP only
```

| Script (Lab 11 name) | Purpose |
| --- | --- |
| `gh-secrets-setup.sh` | One-time, local: the OIDC identity and the `AZURE_*` GitHub secrets |
| `env-setup.sh` | Resource group, with generated names stored as its tags |
| `build-images.sh` | Container registry and the `tripgenie-acr-pull` identity the apps pull with, then build and push every service image |
| `deploy-azure-env.sh` | Container Apps environment |
| `deploy-azure.sh` | Every service, as a container app, each confirmed running its new image |
| `deployment-testing.sh` | Validates the deployment and writes `docs/reports/release-2/cloud-deployment-results.md` |
| `cleanup.sh` | Deletes the resource group to stop billing |

Helpers: `compose_to_azure.py` reads `docker compose config` and renders the
image list and each app's `az containerapp create` arguments. `smoke_test.py`
holds the checks `deployment-testing.sh` runs.

## Where TripGenie differs from Lab 11

- **Sign-in identity.** A managed identity, not an Entra app registration. The UTS tenant blocks students from registering apps.
- **OIDC subject.** `gh-secrets-setup.sh` trusts the subject GitHub reports for the repository (`GET repos/{repo}/actions/oidc/customization/sub`, its `sub_claim_prefix` plus `:environment:production`), not one built from the `origin` remote. The remote may still use a name from before the repository was transferred; the script follows GitHub's redirect to the current name. It stops before changing Azure if GitHub cannot report the subject or the repository uses a custom subject template.
- **Registry pull identity.** Apps pull with the user-assigned identity `tripgenie-acr-pull`, which holds `AcrPull` on the registry only. Lab 11's `--registry-identity system` makes `az containerapp create` replace the app with Microsoft's quickstart image and no registry, then send the real image in a second request. Every redeploy then created a placeholder revision that failed to start, and an app was left on it whenever the second request never arrived (see [Failed placeholder revisions](#failed-placeholder-revisions)).
- **Deployment gate.** `deploy-azure.sh` reports success only when each app's newest revision runs the image just pushed and Azure reports it as the latest *ready* revision. A revision that fails to start leaves the previous one serving traffic while the app still shows `Running`/`Succeeded`, so those states alone prove nothing.
- **Image builds.** Docker build and push, not `az acr build`. Azure for Students rejects ACR Tasks (`TasksOperationsNotAllowed`).
- **App list.** Eighteen apps rendered from `docker-compose.yml`, not three listed by hand. A new service, port or env var reaches the cloud without editing a script.
- **Environment type.** Created through the API as a standard *WorkloadProfiles* environment. On this subscription `az containerapp env create` creates an *express* environment, even with `--enable-workload-profiles`, and express has no TCP ingress, service discovery or registry managed identity.
- **One environment per region.** Azure for Students allows only one Container Apps environment per region. Delete a broken one (or run `cleanup.sh`) and let the deletion finish before creating another.
- **Internal ingress.** Backends and databases get internal **TCP** ingress on their compose port, so service URLs such as `http://student-1-database:8002` work unchanged.
- **Database data.** As in Lab 11, databases keep their SQLite file only for the life of their single replica. A restart or redeploy restores the seed data.
- **HTTPS behind ingress.** Azure ingress ends TLS and forwards plain HTTP, so the frontends trust its `X-Forwarded-*` headers in the cloud profile only (`TRIPGENIE_FORWARDED_ALLOW_IPS=*` in `shared/configuration/.env.cloud`, passed as `FORWARDED_ALLOW_IPS`). Their generated links then use `https://`. Locally the default stays `127.0.0.1`.

## One-time setup (subscription owner)

```bash
az login                                      # Azure for Students subscription
bash scripts/deploy/azure/gh-secrets-setup.sh
```

Then create the GitHub environment **`production`** with a required reviewer.
Its approval is the human release decision for each cloud deployment.

Rerunning the script is safe: it re-syncs the federated credential to the
subject GitHub reports now, keeps the role assignments on `rg-tripgenie`, and
stores only IDs (never a credential) in the `AZURE_*` secrets.

## Deploy

- **From GitHub (any teammate):** go to **Actions → Cloud Deployment → Run workflow**. Every service's CI runs first, then the `production` approval gate, then the scripts below. Download the `cloud-deployment-evidence` artifact afterwards.
- **From a laptop** (needs `az login` and Docker):
  ```bash
  bash scripts/deploy/azure/env-setup.sh
  bash scripts/deploy/azure/build-images.sh
  bash scripts/deploy/azure/deploy-azure-env.sh
  bash scripts/deploy/azure/deploy-azure.sh        # FRONTEND_MIN_REPLICAS=1 avoids cold starts
  bash scripts/deploy/azure/deployment-testing.sh
  ```

Cost: the twelve internal apps run one replica each, about US$2 a day while
deployed. Frontends scale to zero.

```bash
bash scripts/deploy/azure/cleanup.sh   # then rerun gh-secrets-setup.sh before the next deploy:
                                      # CI's roles are scoped to the deleted resource group
```

## Failed placeholder revisions

Deployments before the registry pull identity could leave an app's newest
revision on `mcr.microsoft.com/k8se/quickstart:latest`, `Unhealthy` and
`ActivationFailed`, with no registry configured, while an older revision kept
serving traffic. Find them with:

```bash
az containerapp list -g rg-tripgenie \
  --query "[?properties.latestRevisionName != properties.latestReadyRevisionName].name" -o tsv
```

The next **Cloud Deployment** run replaces each app in a single request with
the real image, the pull identity and its full configuration, and fails if any
app does not end on a ready revision of that image. The apps' old
system-assigned identities are removed, which leaves their `AcrPull`
assignments on the registry as harmless *Identity not found* entries that may
be deleted.

Tests in `tests/ci/test_azure_deploy_scripts.py` run these scripts against
stub `az`, `gh` and `docker` commands. They check what the scripts do, not
that a real deployment works; only a Cloud Deployment run shows that.
