#!/bin/bash
# Read the generated gateway public key through AWS Systems Manager.
# Usage: ./scripts/get-wireguard-server-key.sh [instance_id] [region]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTANCE_ID="${1:-$(terraform -chdir="${REPO_ROOT}/infra/aws" output -raw wireguard_instance_id)}"
REGION="${2:-${AWS_REGION:-${AWS_DEFAULT_REGION:-eu-west-1}}}"

COMMAND_ID="$(
    aws ssm send-command \
        --region "${REGION}" \
        --instance-ids "${INSTANCE_ID}" \
        --document-name AWS-RunShellScript \
        --parameters '{"commands":["sudo cat /etc/wireguard/server_public.key"]}' \
        --query 'Command.CommandId' \
        --output text
)"

aws ssm wait command-executed \
    --region "${REGION}" \
    --command-id "${COMMAND_ID}" \
    --instance-id "${INSTANCE_ID}"

aws ssm get-command-invocation \
    --region "${REGION}" \
    --command-id "${COMMAND_ID}" \
    --instance-id "${INSTANCE_ID}" \
    --query 'StandardOutputContent' \
    --output text | tr -d '\r\n'
echo
