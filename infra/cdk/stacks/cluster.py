"""k3s cluster on EC2 — master + optional worker nodes.

CDK provisions the EC2 instances and networking only.
Workloads (EEP, IEP3, Redis, Nginx) are deployed separately via kubectl
using the manifests in infra/cloud/.

The k3s token and kubeconfig are stored in SSM Parameter Store
so worker nodes and CI/CD can retrieve them without manual copy-paste.
"""
from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_iam as iam
from aws_cdk import aws_ssm as ssm
from constructs import Construct

_MASTER_USERDATA = r"""#!/bin/bash
set -e

# ── k3s server ────────────────────────────────────────────────────────────────
curl -sfL https://get.k3s.io | sh -s - \
  --disable traefik \
  --write-kubeconfig-mode 644

# Wait for k3s to be ready
until kubectl get nodes 2>/dev/null | grep -q Ready; do sleep 3; done

# ── Store join token in SSM ───────────────────────────────────────────────────
TOKEN=$(cat /var/lib/rancher/k3s/server/node-token)
REGION=$(curl -sf http://169.254.169.254/latest/meta-data/placement/region)
aws ssm put-parameter \
  --region "$REGION" \
  --name /retail-edge/k3s-token \
  --value "$TOKEN" \
  --type SecureString \
  --overwrite

MASTER_IP=$(curl -sf http://169.254.169.254/latest/meta-data/local-ipv4)
aws ssm put-parameter \
  --region "$REGION" \
  --name /retail-edge/k3s-master-ip \
  --value "$MASTER_IP" \
  --type String \
  --overwrite

# ── Install Helm + KEDA (for IEP2 edge workers) ───────────────────────────────
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm install keda kedacore/keda --namespace keda --create-namespace

# ── Nginx Ingress (pinned version; retry until k3s API is ready) ───────────────
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
until kubectl apply -f \
  https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.3/deploy/static/provider/cloud/deploy.yaml; do
  echo "ingress-nginx apply failed, retrying in 10s..."
  sleep 10
done
"""

_WORKER_USERDATA = r"""#!/bin/bash
set -e
REGION=$(curl -sf http://169.254.169.254/latest/meta-data/placement/region)

TOKEN=$(aws ssm get-parameter --region "$REGION" \
  --name /retail-edge/k3s-token --with-decryption \
  --query Parameter.Value --output text)

MASTER_IP=$(aws ssm get-parameter --region "$REGION" \
  --name /retail-edge/k3s-master-ip \
  --query Parameter.Value --output text)

curl -sfL https://get.k3s.io | K3S_URL="https://${MASTER_IP}:6443" \
  K3S_TOKEN="$TOKEN" sh -
"""


class ClusterStack(Stack):
    def __init__(self, scope: Construct, id: str, *, vpc: ec2.Vpc, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # ── IAM role for EC2 nodes (SSM access) ───────────────────────────────
        role = iam.Role(
            self, "NodeRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMFullAccess"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEC2ContainerRegistryReadOnly"),
            ],
        )

        # ── Security group ────────────────────────────────────────────────────
        self.sg = ec2.SecurityGroup(self, "ClusterSg", vpc=vpc, description="k3s cluster")
        self.sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "HTTP")
        self.sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS")
        self.sg.add_ingress_rule(ec2.Peer.ipv4(vpc.vpc_cidr_block), ec2.Port.tcp(6443), "k3s API")
        self.sg.add_ingress_rule(ec2.Peer.ipv4(vpc.vpc_cidr_block), ec2.Port.tcp(6379), "Redis")
        self.sg.add_ingress_rule(ec2.Peer.ipv4(vpc.vpc_cidr_block), ec2.Port.tcp(10250), "kubelet")

        # ── Master node (runs EEP, Redis, Nginx Ingress) ──────────────────────
        # Allocate the EIP first so we can bake its IP into the k3s TLS SANs —
        # the serving cert must be valid for the public IP clients connect to.
        master_eip = ec2.CfnEIP(self, "MasterEip", domain="vpc")

        master_ud = ec2.UserData.for_linux()
        # Write k3s config with tls-san BEFORE install so the serving cert
        # includes the public Elastic IP (no insecure-skip-tls-verify needed).
        master_ud.add_commands(
            "mkdir -p /etc/rancher/k3s",
            f"printf 'tls-san:\\n  - %s\\n' {master_eip.ref} > /etc/rancher/k3s/config.yaml",
        )
        master_ud.add_commands(_MASTER_USERDATA)

        master = ec2.Instance(
            self, "Master",
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T3, ec2.InstanceSize.MEDIUM
            ),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=self.sg,
            role=role,
            user_data=master_ud,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(30),
                )
            ],
        )
        ec2.CfnEIPAssociation(
            self, "MasterEipAssoc",
            allocation_id=master_eip.attr_allocation_id,
            instance_id=master.instance_id,
        )

        # ── Worker node (runs IEP3 pods — one per store) ──────────────────────
        worker_ud = ec2.UserData.for_linux()
        worker_ud.add_commands(_WORKER_USERDATA)

        ec2.Instance(
            self, "Worker",
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T3, ec2.InstanceSize.SMALL
            ),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=self.sg,
            role=role,
            user_data=worker_ud,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(20),
                )
            ],
        )

        self.master_public_ip: str = master_eip.ref
        self.master_private_ip: str = master.instance_private_ip

        # ── CodeBuild — builds Docker images inside AWS, pushes to ECR ───────
        # One reusable project; caller passes SERVICE, DOCKERFILE, ECR_REPO
        # as environment variable overrides per build.
        build_role = iam.Role(
            self, "BuildRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonEC2ContainerRegistryPowerUser"
                ),
            ],
        )

        codebuild.Project(
            self, "BuildProject",
            project_name="retail-edge-build",
            role=build_role,
            source=codebuild.Source.git_hub(
                owner="Salman-719",
                repo="retail-edge",
                branch_or_ref="codex/salman-marji-alignment",
                # Requires a GitHub OAuth connection configured in the AWS Console:
                # Developer Tools → Settings → Connections → Create connection (GitHub)
                # After connecting, re-run: cdk deploy RetailEdgeCluster
            ),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,  # required for Docker-in-Docker
            ),
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "pre_build": {
                        "commands": [
                            "aws ecr get-login-password --region $AWS_DEFAULT_REGION"
                            " | docker login --username AWS --password-stdin"
                            " $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com",
                        ]
                    },
                    "build": {
                        "commands": [
                            "docker build -f $DOCKERFILE -t $ECR_REPO:$CODEBUILD_RESOLVED_SOURCE_VERSION .",
                            "docker tag $ECR_REPO:$CODEBUILD_RESOLVED_SOURCE_VERSION $ECR_REPO:latest",
                        ]
                    },
                    "post_build": {
                        "commands": [
                            "docker push $ECR_REPO:$CODEBUILD_RESOLVED_SOURCE_VERSION",
                            "docker push $ECR_REPO:latest",
                        ]
                    },
                },
            }),
        )

        CfnOutput(self, "MasterPublicIp", value=master_eip.ref,
                  description="k3s master public IP — use as EEP_BASE_URL and Ingress target")
        CfnOutput(self, "KubeconfigCommand",
                  value=f"ssh ec2-user@{master_eip.ref} 'sudo cat /etc/rancher/k3s/k3s.yaml'",
                  description="Retrieve kubeconfig from master node")
