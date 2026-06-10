# CI/CD Secrets Reference

All secrets are stored in **GitHub → Settings → Secrets and variables → Actions**.
Secrets marked **Environment** must also be added under the `production` GitHub
Environment (Settings → Environments → production → Environment secrets) so that
Jobs 3–7, which use `environment: production`, can read them.

---

## Required secrets

### Container registry

| Secret name | Scope | What it should contain |
|---|---|---|
| `REGISTRY_USERNAME` | Repository | Your GitHub username (or a machine account with `write:packages` permission on GHCR). Used by `docker/login-action` to push images to `ghcr.io`. |
| `REGISTRY_PASSWORD` | Repository | A GitHub Personal Access Token (classic) with `write:packages` scope. Generate at GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic). |

### Deploy host (SSH)

| Secret name | Scope | What it should contain |
|---|---|---|
| `DEPLOY_HOST` | Environment | Hostname or IP of the production server (e.g. `retailvision.example.com`). The pipeline SSHs to this host to pull images and restart services. |
| `DEPLOY_USER` | Environment | SSH username on the deploy host (e.g. `ubuntu` or `deploy`). This user must be in the `docker` group. |
| `DEPLOY_SSH_KEY` | Environment | The **private** half of an Ed25519 key pair. Generate with: `ssh-keygen -t ed25519 -C "github-actions" -f deploy_key`. Copy the contents of `deploy_key` (private) here. Add `deploy_key.pub` to `~/.ssh/authorized_keys` on the server. **Never** commit either file. |

### MLflow

| Secret name | Scope | What it should contain |
|---|---|---|
| `MLFLOW_TRACKING_URI` | Environment | Full URL to your MLflow tracking server, e.g. `http://mlflow.internal:5000`. Must be reachable from the GitHub Actions runner. For self-hosted runners on your VPC this is straightforward; for hosted runners you need a public endpoint or VPN. |

### Prometheus & Grafana

| Secret name | Scope | What it should contain |
|---|---|---|
| `PROMETHEUS_URL` | Environment | Base URL of the Prometheus server, e.g. `http://prometheus.internal:9090`. Used by `canary_eval.py` (Job 4) and the target health check (Job 6). |
| `GRAFANA_PASSWORD` | Environment | Grafana admin password. Matches `GRAFANA_PASSWORD` in your `.env` / compose file. Used only for the Job 6 `/api/health` check (read-only). |

### Application secrets (passed to containers on deploy)

These are not read directly by the pipeline YAML but are needed by the
`docker compose up` command on the deploy host. They must exist in the
server's `/opt/retailvision/.env` file **or** be exported in the deploy
user's shell environment before `docker compose` runs.

| Secret name | What it should contain |
|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL password for the `retailvision` user. |
| `DATABASE_URL_EEP` | Full `postgresql+asyncpg://` connection string for the EEP service. |
| `JWT_SECRET` | Random 32-byte hex string. Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `S3_ACCESS_KEY` | MinIO / S3 access key (root user). |
| `S3_SECRET_KEY` | MinIO / S3 secret key (root password). |

### Notifications

| Secret name | Scope | What it should contain |
|---|---|---|
| `SLACK_WEBHOOK_URL` | Repository | Incoming Webhook URL from your Slack app. Create at api.slack.com → Your Apps → Incoming Webhooks → Add New Webhook. The rollback job (Job 7) posts to this URL on any pipeline failure. Set to a dummy value (e.g. `https://hooks.slack.com/disabled`) if you do not want Slack notifications — the step uses `continue-on-error` implicitly via the slack action's own error handling. |

---

## How to override window durations for production

The pipeline sets short CI defaults at the top of `promotion.yml`:

```yaml
env:
  SHADOW_WINDOW_SECONDS: "30"
  CANARY_WINDOW_SECONDS: "60"
```

To use longer production windows **without editing the YAML**, add these as
**Environment variables** (not secrets — they are not sensitive) in the
`production` GitHub Environment:

| Variable | CI default | Recommended production value |
|---|---|---|
| `SHADOW_WINDOW_SECONDS` | `30` | `300` (5 minutes) |
| `CANARY_WINDOW_SECONDS` | `60` | `1800` (30 minutes) |
| `CANARY_PERCENTAGE` | `10` | `10`–`25` depending on traffic |
| `CANARY_LOOKBACK_MINUTES` | `5` | `30` |

GitHub Environment variables override workflow-level `env:` values when the
job specifies `environment: production`.

---

## How to create secrets

```bash
# Using the GitHub CLI (gh):
gh secret set REGISTRY_USERNAME   --body "your-github-username"
gh secret set REGISTRY_PASSWORD   --body "ghp_xxxxxxxxxxxxxxxxxxxx"
gh secret set DEPLOY_HOST         --env production --body "retailvision.example.com"
gh secret set DEPLOY_USER         --env production --body "ubuntu"
gh secret set DEPLOY_SSH_KEY      --env production < ~/.ssh/deploy_key
gh secret set MLFLOW_TRACKING_URI --env production --body "http://mlflow.internal:5000"
gh secret set PROMETHEUS_URL      --env production --body "http://prometheus.internal:9090"
gh secret set GRAFANA_PASSWORD    --env production --body "your-grafana-admin-password"
gh secret set SLACK_WEBHOOK_URL   --body "https://hooks.slack.com/services/T.../B.../xxx"
```

Or navigate to: **GitHub repo → Settings → Secrets and variables → Actions → New repository secret**.

For environment secrets: **Settings → Environments → production → Add secret**.
