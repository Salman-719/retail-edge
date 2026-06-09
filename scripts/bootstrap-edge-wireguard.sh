#!/bin/bash
# Configure a store edge device to route only the RetailVision VPC through
# WireGuard. Run as root after the cloud gateway exists.
#
# Usage:
#   sudo ./bootstrap-edge-wireguard.sh \
#     <gateway_public_ip:port> <gateway_public_key> <edge_tunnel_ip>
#
# Optional env:
#   RETAILVISION_VPC_CIDR  defaults to 10.20.0.0/16
set -euo pipefail

if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <gateway_public_ip:port> <gateway_public_key> <edge_tunnel_ip>"
    exit 2
fi

GATEWAY_ENDPOINT=$1
GATEWAY_PUBLIC_KEY=$2
EDGE_TUNNEL_IP=${3%/32}
RETAILVISION_VPC_CIDR="${RETAILVISION_VPC_CIDR:-10.20.0.0/16}"

if ! [[ "${GATEWAY_PUBLIC_KEY}" =~ ^[A-Za-z0-9+/]{43}=$ ]]; then
    echo "ERROR: invalid WireGuard gateway public key"
    exit 2
fi
if ! [[ "${GATEWAY_ENDPOINT}" =~ ^[^:[:space:]]+:[0-9]+$ ]]; then
    echo "ERROR: gateway endpoint must be host:port"
    exit 2
fi
if ! [[ "${EDGE_TUNNEL_IP}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: edge_tunnel_ip must be an IPv4 address, for example 10.99.0.2"
    exit 2
fi
if ! [[ "${RETAILVISION_VPC_CIDR}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]]; then
    echo "ERROR: RETAILVISION_VPC_CIDR must be an IPv4 CIDR"
    exit 2
fi

apt-get update
apt-get install -y wireguard

install -d -m 0700 /etc/wireguard
umask 077
if [ ! -s /etc/wireguard/private.key ]; then
    wg genkey > /etc/wireguard/private.key
fi
wg pubkey < /etc/wireguard/private.key > /etc/wireguard/public.key

PRIVATE_KEY="$(cat /etc/wireguard/private.key)"
cat > /etc/wireguard/wg0.conf << EOF
[Interface]
Address = ${EDGE_TUNNEL_IP}/32
PrivateKey = ${PRIVATE_KEY}

[Peer]
PublicKey = ${GATEWAY_PUBLIC_KEY}
Endpoint = ${GATEWAY_ENDPOINT}
AllowedIPs = ${RETAILVISION_VPC_CIDR}
PersistentKeepalive = 25
EOF
chmod 0600 /etc/wireguard/wg0.conf

systemctl enable wg-quick@wg0
systemctl restart wg-quick@wg0

echo
echo "Edge WireGuard public key:"
cat /etc/wireguard/public.key
echo
echo "Register that key in AWS with tunnel IP ${EDGE_TUNNEL_IP}, then verify:"
echo "  sudo wg show wg0"
