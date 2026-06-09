#!/bin/bash
set -euxo pipefail

dnf install -y wireguard-tools iptables-nft iptables-services

install -d -m 0700 /etc/wireguard
umask 077

if [ ! -s /etc/wireguard/server_private.key ]; then
  wg genkey > /etc/wireguard/server_private.key
fi
wg pubkey < /etc/wireguard/server_private.key > /etc/wireguard/server_public.key

PRIVATE_KEY="$(cat /etc/wireguard/server_private.key)"
PUBLIC_IFACE="$(ip route show default | awk '{print $5; exit}')"

cat > /etc/sysctl.d/99-retailvision-wireguard.conf <<'SYSCTL'
net.ipv4.ip_forward = 1
SYSCTL
sysctl --system

cat > /etc/wireguard/wg0.conf <<EOF
[Interface]
Address = ${server_address}
ListenPort = ${listen_port}
PrivateKey = $PRIVATE_KEY
SaveConfig = true
PostUp = iptables -A FORWARD -i wg0 -o $PUBLIC_IFACE -d ${vpc_cidr} -j ACCEPT
PostUp = iptables -A FORWARD -i $PUBLIC_IFACE -o wg0 -s ${vpc_cidr} -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
PostUp = iptables -t nat -A POSTROUTING -s ${tunnel_cidr} -d ${vpc_cidr} -o $PUBLIC_IFACE -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -o $PUBLIC_IFACE -d ${vpc_cidr} -j ACCEPT
PostDown = iptables -D FORWARD -i $PUBLIC_IFACE -o wg0 -s ${vpc_cidr} -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -s ${tunnel_cidr} -d ${vpc_cidr} -o $PUBLIC_IFACE -j MASQUERADE
EOF
chmod 0600 /etc/wireguard/wg0.conf

cat > /usr/local/bin/retailvision-wg-peer <<'PEER'
#!/bin/bash
set -euo pipefail

if [ "$#" -ne 3 ] || [ "$1" != "add" ]; then
  echo "Usage: $0 add <peer-public-key> <peer-ip>" >&2
  exit 2
fi

peer_key="$2"
peer_ip="$3"

if ! [[ "$peer_key" =~ ^[A-Za-z0-9+/]{43}=$ ]]; then
  echo "Invalid WireGuard public key" >&2
  exit 2
fi
case "$peer_ip" in
  ${tunnel_prefix}.*) ;;
  *)
    echo "Peer IP must be inside ${tunnel_prefix}.0/24" >&2
    exit 2
    ;;
esac
peer_host="$(printf '%s' "$peer_ip" | awk -F. '{print $4}')"
if [ "$peer_host" -lt 2 ] || [ "$peer_host" -gt 254 ]; then
  echo "Peer host number must be between 2 and 254" >&2
  exit 2
fi

existing_key="$(wg show wg0 allowed-ips | awk -v ip="$peer_ip/32" '$2 == ip {print $1; exit}')"
if [ -n "$existing_key" ] && [ "$existing_key" != "$peer_key" ]; then
  echo "Peer IP $peer_ip is already assigned to another public key" >&2
  exit 2
fi

wg set wg0 peer "$peer_key" allowed-ips "$peer_ip/32"
wg-quick save wg0
wg show wg0
PEER
chmod 0755 /usr/local/bin/retailvision-wg-peer

systemctl enable --now wg-quick@wg0
