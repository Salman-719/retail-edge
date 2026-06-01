from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from constructs import Construct


class DataStack(Stack):
    def __init__(self, scope, id: str, *, vpc: ec2.Vpc, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # ── S3 — vision frames ────────────────────────────────────────────────
        # Used only when IEP1_FRAME_STORAGE=s3 (multi-node deployments).
        # For co-located IEP1+IEP2 on Jetson use filesystem — no S3 round-trip.
        # 2-hour expiry: frames are consumed by IEP2 within seconds of upload.
        self.frames_bucket = s3.Bucket(
            self, "FramesBucket",
            removal_policy=RemovalPolicy.RETAIN,
            encryption=s3.BucketEncryption.S3_MANAGED,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-vision-frames",
                    enabled=True,
                    prefix="vision-frames/",
                    expiration=Duration.hours(2),
                ),
            ],
        )

        # ── RDS PostgreSQL 15 ─────────────────────────────────────────────────
        # Written by IEP2 (Jetson, via WireGuard VPN) and read by IEP3 + EEP.
        self.db_sg = ec2.SecurityGroup(
            self, "DbSg", vpc=vpc, description="RDS PostgreSQL"
        )
        # Allow from VPC (EEP, IEP3 Fargate)
        self.db_sg.add_ingress_rule(
            ec2.Peer.ipv4(vpc.vpc_cidr_block), ec2.Port.tcp(5432), "VPC → RDS"
        )
        # Allow from WireGuard VPN subnet (IEP2 on Jetson)
        self.db_sg.add_ingress_rule(
            ec2.Peer.ipv4("10.200.0.0/24"), ec2.Port.tcp(5432), "VPN → RDS"
        )

        self._db = rds.DatabaseInstance(
            self, "Postgres",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_15
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T3, ec2.InstanceSize.MICRO
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            security_groups=[self.db_sg],
            database_name="retailvision",
            credentials=rds.Credentials.from_generated_secret("retailvision"),
            removal_policy=RemovalPolicy.SNAPSHOT,
            deletion_protection=True,
            storage_encrypted=True,
            backup_retention=Duration.days(7),
            multi_az=False,
        )
        self.db_secret = self._db.secret
