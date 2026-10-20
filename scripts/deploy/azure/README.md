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
| `build-images.sh` | Container registry, then build and push every service image |
| `deploy-azure-env.sh` | Container Apps environment |
| `deploy-azure.sh` | Every service, as a container app |
| `deployment-testing.sh` | Validates the deployment and writes `docs/reports/release-2/cloud-deployment-results.md` |
| `cleanup.sh` | Deletes the resource group to stop billing |

Helpers: `compose_to_azure.py` reads `docker compose config` and renders the
image list and each app's `az containerapp create` arguments. `smoke_test.py`
holds the checks `deployment-testing.sh` runs.

## Where TripGenie differs from Lab 11

- **Sign-in identity.** A managed identity, not an Entra app registration. The UTS tenant blocks students from registering apps.
- **Image builds.** Docker build and push, not `az acr build`. Azure for Students rejects ACR Tasks (`TasksOperationsNotAllowed`).
- **App list.** Eighteen apps rendered from `docker-compose.yml`, not three listed by hand. A new service, port or env var reaches the cloud without editing a script.
- **Environment type.** Created through the API as a standard *WorkloadProfiles* environment. On this subscription `az containerapp env create` creates an *express* environment, even with `--enable-workload-profiles`, and express has no TCP ingress, service discovery or registry managed identity.
- **One environment per region.** Azure for Students allows only one Container Apps environment per region. Delete a broken one (or run `cleanup.sh`) and let the deletion finish before creating another.
- **Internal ingress.** Backends and databases get internal **TCP** ingress on their compose port, so service URLs such as `http://student-1-database:8002` work unchanged.
- **Database data.** As in Lab 11, databases keep their SQLite file only for the life of their single replica. A restart or redeploy restores the seed data.

## One-time setup (subscription owner)

```bash
az login                                      # Azure for Students subscription
bash scripts/deploy/azure/gh-secrets-setup.sh
```

Then create the GitHub environment **`production`** with a required reviewer.
Its approval is the human release decision for each cloud deployment.

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
