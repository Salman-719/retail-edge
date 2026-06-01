"""WireGuard VPN gateway + Redis on a single t3.micro.

Jetsons connect to the WireGuard endpoint and receive a VPN IP inside
10.200.0.0/24, giving them private access to:
  - This EC2's Redis (port 6379) for the IEP2→IEP3 batch_complete stream
  - RDS (port 5432) for tracking_history writes from IEP2

Redis also serves EEP and IEP3 Fargate tasks via the EC2's VPC private IP
(no VPN needed within the VPC).

Key exchange is manual per Jetson — see infra/edge/README.md.
"""
from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_ec2 as ec2
from constructs import Construct

_USER_DATA = r"""#!/bin/bash
set -e
apt-get update -y
apt-get install -y wireguard redis-server iproute2

# ── Redis — bind to all interfaces so VPN clients can reach it ────────────
sed -i 's/^bind 127.0.0.1 -1/bind 0.0.0.0/' /etc/redis/redis.conf
systemctl enable redis-server
systemctl start redis-server

# ── WireGuard — server side ───────────────────────────────────────────────
# Generate server keys (done once; rotate via SSM if needed)
wg genkey | tee /etc/wireguard/server_private.key | wg pubkey \
  > /etc/wireguard/server_public.key
chmod 600 /etc/wireguard/server_private.key

SERVER_PRIV=$(cat /etc/wireguard/server_private.key)

# Each Jetson gets its own [Peer] block added here after key exchange.
# See infra/edge/README.md for the manual steps.
cat > /etc/wireguard/wg0.conf <<EOF
[Interface]
Address = 10.200.0.1/24
ListenPort = 51820
PrivateKey = ${SERVER_PRIV}
PostUp   = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# Add Jetson peers here after running: wg genkey | tee jetson.key | wg pubkey > jetson.pub
# [Peer]
# PublicKey = <JETSON_PUBLIC_KEY>
# AllowedIPs = 10.200.0.2/32
EOF

sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0

# Print public key to system log so it can be retrieved via CloudWatch
echo "WireGuard server public key: $(cat /etc/wireguard/server_public.key)"
"""


class VpnStack(Stack):
    def __init__(self, scope, id: str, *, vpc: ec2.Vpc, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        self.sg = ec2.SecurityGroup(
            self, "VpnSg", vpc=vpc, description="WireGuard VPN + Redis"
        )
        # WireGuard — Jetsons connect from internet
        self.sg.add_ingress_rule(
            ec2.Peer.any_ipv4(), ec2.Port.udp(51820), "WireGuard"
        )
        # Redis — VPC internal (EEP, IEP3 Fargate tasks)
        self.sg.add_ingress_rule(
            ec2.Peer.ipv4(vpc.vpc_cidr_block), ec2.Port.tcp(6379), "Redis from VPC"
        )
        # Redis — WireGuard VPN subnet (IEP2 on Jetson)
        self.sg.add_ingress_rule(
            ec2.Peer.ipv4("10.200.0.0/24"), ec2.Port.tcp(6379), "Redis from VPN"
        )
        # RDS access routed through this gateway — allow VPN subnet to be
        # forwarded; RDS SG will allow from VPN subnet separately.

        eip = ec2.CfnEIP(self, "VpnEip")

        user_data = ec2.UserData.for_linux()
        user_data.add_commands(_USER_DATA)

        instance = ec2.Instance(
            self, "VpnNode",
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T3, ec2.InstanceSize.MICRO
            ),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=self.sg,
            user_data=user_data,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(10),
                )
            ],
        )

        ec2.CfnEIPAssociation(
            self, "VpnEipAssoc",
            eip=eip.ref,
            instance_id=instance.instance_id,
        )

        # Redis is on this EC2's private IP — reachable from Fargate in VPC
        self.redis_host: str = instance.instance_private_ip
        # Stable public IP for Jetson WireGuard config
        self.vpn_public_ip: str = eip.ref

        CfnOutput(self, "VpnPublicIp", value=eip.ref,
                  description="WireGuard endpoint — set in Jetson wg0.conf")
        CfnOutput(self, "RedisPrivateIp", value=instance.instance_private_ip,
                  description="Redis host for EEP and IEP3 (VPC internal)")
