#!/bin/bash
# Enrol an edge WireGuard public key on the SSM-managed gateway.
#
# Usage:
#   ./scripts/register-edge-wireguard-peer.sh \
#     <edge_public_key> <edge_tunnel_ip> [instance_id] [region]
set -euo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 4 ]; then
    echo "Usage: $0 <edge_public_key> <edge_tunnel_ip> [instance_id] [region]"
    exit 2
fi

EDGE_PUBLIC_KEY=$1
EDGE_TUNNEL_IP=${2%/32}
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTANCE_ID="${3:-$(terraform -chdir="${REPO_ROOT}/infra/aws" output -raw wireguard_instance_id)}"
REGION="${4:-${AWS_REGION:-${AWS_DEFAULT_REGION:-eu-west-1}}}"

if ! [[ "${EDGE_PUBLIC_KEY}" =~ ^[A-Za-z0-9+/]{43}=$ ]]; then
    echo "ERROR: invalid WireGuard edge public key"
    exit 2
fi
if ! [[ "${EDGE_TUNNEL_IP}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: edge_tunnel_ip must be an IPv4 address"
    exit 2
fi

PARAMETERS="$(
    printf '{"commands":["sudo /usr/local/bin/retailvision-wg-peer add %s %s"]}' \
        "${EDGE_PUBLIC_KEY}" "${EDGE_TUNNEL_IP}"
)"
COMMAND_ID="$(
    aws ssm send-command \
        --region "${REGION}" \
        --instance-ids "${INSTANCE_ID}" \
        --document-name AWS-RunShellScript \
        --parameters "${PARAMETERS}" \
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
    --query '{status:Status,stdout:StandardOutputContent,stderr:StandardErrorContent}' \
    --output yaml
