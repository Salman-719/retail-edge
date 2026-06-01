#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.network import NetworkStack
from stacks.data import DataStack
from stacks.cluster import ClusterStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account") or None,
    region=app.node.try_get_context("region") or "me-south-1",
)

network = NetworkStack(app, "RetailEdgeNetwork", env=env)
data = DataStack(app, "RetailEdgeData", vpc=network.vpc, env=env)
ClusterStack(app, "RetailEdgeCluster", vpc=network.vpc, env=env)

# Workloads (EEP, IEP3, Redis, Nginx) are deployed via:
#   kubectl apply -k infra/cloud/
# after retrieving the kubeconfig from the master node.

app.synth()
