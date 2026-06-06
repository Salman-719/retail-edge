#!/bin/bash
# EC2 user-data for the k3s SERVER node. Clones the repo and runs the cloud
# bootstrap, which installs k3s + add-ons and is ready for `helm install`.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git

export AWS_REGION="${aws_region}"
export APP_HOST="${app_host}"
export EEP_HOST="${eep_host}"
export LETSENCRYPT_EMAIL="${letsencrypt_email}"
export K3S_TOKEN="${k3s_token}"
export K3S_VERSION="${k3s_version}"

git clone --branch "${git_branch}" "${git_repo_url}" /opt/retail-edge
cd /opt/retail-edge
bash scripts/bootstrap-cloud-k3s.sh
