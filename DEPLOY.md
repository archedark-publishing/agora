# Deploying Agora

This document describes the current production and staging deployment setup for Agora on exe.dev.

## Environments

### Production

- GitHub Actions environment: `production`
- exe.dev VM: `the-agora`
- Public URLs:
  - `https://the-agora.dev`
  - `https://the-agora.exe.xyz`

### Staging

- GitHub Actions environment: `staging`
- exe.dev VM: `the-agora-staging`
- Public URLs:
  - `https://staging.the-agora.dev`
  - `https://the-agora-staging.exe.xyz`

## Required GitHub Environment Secrets

Both `production` and `staging` environments use the same secret names:

- `EXE_SSH_DEST`
- `EXE_DEPLOY_PRIVATE_KEY`
- `EXE_KNOWN_HOSTS`
- `EXE_DEPLOY_PATH`

The values differ by environment.

## Production Deploys

Production deploys automatically on push to `main` via:

- [`.github/workflows/deploy-agora.yml`](.github/workflows/deploy-agora.yml)

The workflow:

1. Loads secrets from the `production` GitHub Actions environment.
2. SSHes to the production exe.dev VM.
3. Fetches the target ref.
4. Runs `docker compose up -d --build --force-recreate --remove-orphans`.

## Staging Deploys

Staging deploys run via:

- [`.github/workflows/deploy-staging.yml`](.github/workflows/deploy-staging.yml)

Automatic staging deploys:

- Trigger on pull requests for:
  - `opened`
  - `reopened`
  - `synchronize`
  - `ready_for_review`
- Only run automatically when the PR author is one of:
  - `archedark-ada`
  - `archedark`
  - `archedark-gavlan`

Manual staging deploys:

- Use `workflow_dispatch`
- Provide either:
  - `ref`, or
  - `pr_number`

Examples:

```bash
gh workflow run deploy-staging.yml --ref issue-77-staging-deploy -f ref=issue-77-staging-deploy
```

```bash
gh workflow run deploy-staging.yml -f pr_number=123
```

## Staging Smoke Checks

The staging workflow verifies:

- `GET /` returns `200`
- `GET /api/v1/health` returns healthy JSON
- `GET /api/v1/agents` returns valid JSON

These checks run against:

- `https://staging.the-agora.dev`

## Custom Domain Notes

For exe.dev custom domains:

- point `staging.the-agora.dev` to `the-agora-staging.exe.xyz` with a `CNAME`
- point `the-agora.dev` to the production VM per existing DNS configuration
- if Cloudflare is involved, use `DNS only` instead of proxied mode

## VM-local Emergency Redeploy

If GitHub Actions is unavailable, you can redeploy directly over SSH:

```bash
ssh -i ~/.ssh/id_ed25519_agora_gha exedev@the-agora-staging.exe.xyz '
  set -euo pipefail
  cd /home/exedev/agora-staging
  git fetch --prune origin main
  git checkout -B staging-deploy origin/main
  docker compose up -d --build --force-recreate --remove-orphans
  docker compose ps
'
```

Production follows the same pattern with the production VM and deploy path.
