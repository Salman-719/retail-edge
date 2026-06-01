import os

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as sm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")


class ServicesStack(Stack):
    def __init__(
        self,
        scope,
        id: str,
        *,
        vpc: ec2.Vpc,
        db_secret: sm.ISecret,
        db_sg: ec2.SecurityGroup,
        redis_host: str,
        vpn_sg: ec2.SecurityGroup,
        frames_bucket: s3.Bucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)

        cluster = ecs.Cluster(self, "Cluster", vpc=vpc, container_insights=True)

        app_sg = ec2.SecurityGroup(self, "AppSg", vpc=vpc, description="ECS tasks")

        # ECS tasks → RDS
        db_sg.add_ingress_rule(app_sg, ec2.Port.tcp(5432), "ECS → RDS")
        # ECS tasks → Redis (on VPN EC2)
        vpn_sg.add_ingress_rule(app_sg, ec2.Port.tcp(6379), "ECS → Redis")

        # ── Shared environment ────────────────────────────────────────────────
        common_env = {
            "REDIS_URL": f"redis://{redis_host}:6379/0",
            "S3_BUCKET": frames_bucket.bucket_name,
            "S3_REGION": self.region,
            "BATCH_WINDOW_SECONDS": "2",
            "REID_MATCH_THRESHOLD": "0.70",
            "GALLERY_MAX_SIZE": "6",
        }
        db_secrets = {
            "DB_HOST": ecs.Secret.from_secrets_manager(db_secret, "host"),
            "DB_PORT": ecs.Secret.from_secrets_manager(db_secret, "port"),
            "DB_NAME": ecs.Secret.from_secrets_manager(db_secret, "dbname"),
            "DB_USER": ecs.Secret.from_secrets_manager(db_secret, "username"),
            "DB_PASS": ecs.Secret.from_secrets_manager(db_secret, "password"),
        }

        # ── EEP — API gateway ─────────────────────────────────────────────────
        # desired_count=2: one task handles traffic while the other restarts.
        # ALB health check drops unhealthy tasks before routing to them.
        eep_image = ecr_assets.DockerImageAsset(
            self, "EepImage",
            directory=os.path.join(_REPO_ROOT, "services", "eep"),
        )
        eep_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "Eep",
            cluster=cluster,
            cpu=512,
            memory_limit_mib=1024,
            desired_count=2,
            assign_public_ip=True,
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_groups=[app_sg],
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_docker_image_asset(eep_image),
                container_port=8000,
                environment=common_env,
                secrets=db_secrets,
                log_driver=ecs.LogDrivers.aws_logs(stream_prefix="eep"),
            ),
            health_check_grace_period=Duration.seconds(60),
            public_load_balancer=True,
        )
        eep_service.target_group.configure_health_check(
            path="/health",
            healthy_threshold_count=2,
            unhealthy_threshold_count=3,
            interval=Duration.seconds(15),
        )
        # Rolling deployment: keep 1 task running during deploys
        eep_service.service.apply_removal_policy(None)
        eep_service.task_definition.default_container.add_environment(
            "EEP_BASE_URL",
            f"http://{eep_service.load_balancer.load_balancer_dns_name}",
        )
        frames_bucket.grant_read_write(eep_service.task_definition.task_role)
        db_secret.grant_read(eep_service.task_definition.task_role)

        # ── IEP3 — cross-camera reconciliation ───────────────────────────────
        # Long-lived background worker. Reads Redis stream for batch_complete
        # events, queries RDS, writes global identities. No public endpoint.
        # Uses consumer groups so it resumes from last-seen stream ID on restart
        # — no events are lost during cold starts.
        iep3_image = ecr_assets.DockerImageAsset(
            self, "Iep3Image",
            directory=_REPO_ROOT,
            file="services/iep3_reconciliation/Dockerfile",
        )
        iep3_task = ecs.FargateTaskDefinition(
            self, "Iep3Task", cpu=512, memory_limit_mib=1024
        )
        iep3_task.add_container(
            "iep3",
            image=ecs.ContainerImage.from_docker_image_asset(iep3_image),
            command=["python", "-m", "services.iep3_reconciliation.app.coordinator"],
            environment={
                **common_env,
                "STORE_ID": self.node.try_get_context("store_id") or "",
            },
            secrets=db_secrets,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="iep3"),
        )
        db_secret.grant_read(iep3_task.task_role)

        ecs.FargateService(
            self, "Iep3",
            cluster=cluster,
            task_definition=iep3_task,
            desired_count=1,
            assign_public_ip=True,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_groups=[app_sg],
        )

        # ── Frontend — CloudFront + S3 ────────────────────────────────────────
        frontend_bucket = s3.Bucket(
            self, "FrontendBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )
        oac = cloudfront.S3OriginAccessControl(self, "FrontendOac")
        distribution = cloudfront.Distribution(
            self, "FrontendCdn",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(
                    frontend_bucket, origin_access_control=oac
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403, response_http_status=200,
                    response_page_path="/index.html",
                ),
                cloudfront.ErrorResponse(
                    http_status=404, response_http_status=200,
                    response_page_path="/index.html",
                ),
            ],
        )
        s3deploy.BucketDeployment(
            self, "FrontendDeploy",
            sources=[s3deploy.Source.asset(
                os.path.join(_REPO_ROOT, "frontend", "dist")
            )],
            destination_bucket=frontend_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        # ── IAM user for Jetson edge nodes (S3 frame uploads) ─────────────────
        edge_user = iam.User(self, "EdgeUser", user_name="retail-edge-jetson")
        frames_bucket.grant_put(edge_user)
        edge_key = iam.CfnAccessKey(
            self, "EdgeKey", user_name=edge_user.user_name
        )

        # ── Outputs ───────────────────────────────────────────────────────────
        CfnOutput(self, "EepUrl",
                  value=f"http://{eep_service.load_balancer.load_balancer_dns_name}",
                  description="EEP API — set as EEP_BASE_URL in edge configmap")
        CfnOutput(self, "FrontendUrl",
                  value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "FramesBucket", value=frames_bucket.bucket_name)
        CfnOutput(self, "EdgeAwsKeyId", value=edge_key.ref)
        CfnOutput(self, "EdgeAwsSecretKey", value=edge_key.attr_secret_access_key)
