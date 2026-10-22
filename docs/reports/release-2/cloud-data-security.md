# B6 Cloud Data Security

TripGenie on Azure Container Apps.

## Controls

| Control | Configuration | Validation |
| --- | --- | --- |
| No stored Azure credential: GitHub Actions signs in with OIDC federation. | `scripts/deploy/azure/gh-secrets-setup.sh`, `.github/workflows/cloud-deployment.yml` | GitHub secrets hold only IDs, never a password or key. |
| Apps pull images with the `tripgenie-acr-pull` managed identity, not a registry password. | `scripts/deploy/azure/build-images.sh`, `compose_to_azure.py` | `security_check.py`: every app's registry has an identity and no `passwordSecretRef`. |
| Registry admin user disabled and anonymous pull disabled. | `az acr create --admin-enabled false` in `build-images.sh` | `security_check.py` (`adminUserEnabled`, `anonymousPullEnabled`). |
| No credential in a plain app setting: any `*_PASSWORD`, `*_SECRET`, `*_TOKEN`, `*_API_KEY`, `*_CREDENTIAL(S)` or `*_CONNECTION_STRING` setting must be a Container Apps secret reference. | All 18 container apps | `security_check.py` |
| Stored data is reachable only by its owning backend: the SQLite databases have no public endpoint. | Internal-only ingress for every `*-database` app | `security_check.py`; `smoke_test.py` expects no 200 from each database on the public domain. |
| Secrets kept out of source control. | Pre-commit `detect-secrets` | `.pre-commit-config.yaml`, run on every commit |

`scripts/deploy/azure/deployment-testing.sh` runs `security_check.py` against
the live Azure configuration after every Cloud Deployment and adds a
**Security Configuration** table to `cloud-deployment-results.md`.

## Evidence

| File | Shows |
| --- | --- |
| [`cloud-security-baseline-before.md`](cloud-security/cloud-security-baseline-before.md) | Live Azure: all six databases (and the backends) return 404 from the internet. |
| [`workflow-policy-ci-tests.txt`](cloud-security/workflow-policy-ci-tests.txt) | 69 tests passed. `tests/ci/test_cloud_security.py` shows `security_check.py` passing a secure configuration and failing on each insecure one (public backend, HTTP allowed, registry password, plain credential, admin user, anonymous pull). |
