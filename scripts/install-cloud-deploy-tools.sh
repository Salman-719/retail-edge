#!/usr/bin/env bash
set -euo pipefail

TERRAFORM_VERSION="${TERRAFORM_VERSION:-1.9.8}"
HELM_VERSION="${HELM_VERSION:-3.15.4}"
KUBECTL_VERSION="${KUBECTL_VERSION:-1.30.0}"
KUBECTL_DATE="${KUBECTL_DATE:-2024-05-12}"

SUDO=()
if ((EUID != 0)); then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "ERROR: run as root or install sudo before running this installer." >&2
    exit 1
  fi
  SUDO=(sudo)
fi

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

install_linux_packages() {
  if command -v yum >/dev/null 2>&1; then
    "${SUDO[@]}" yum install -y unzip tar gzip git jq curl make
  elif command -v dnf >/dev/null 2>&1; then
    "${SUDO[@]}" dnf install -y unzip tar gzip git jq curl make
  elif command -v apt-get >/dev/null 2>&1; then
    "${SUDO[@]}" apt-get update
    "${SUDO[@]}" apt-get install -y unzip tar gzip git jq curl make
  else
    echo "ERROR: no supported Linux package manager found. Install unzip tar gzip git jq curl make manually." >&2
    exit 1
  fi
}

install_linux_binaries() {
  local machine bin_arch
  machine="$(uname -m)"
  case "$machine" in
    x86_64) bin_arch="amd64" ;;
    aarch64|arm64) bin_arch="arm64" ;;
    *)
      echo "ERROR: unsupported Linux architecture: $machine" >&2
      exit 1
      ;;
  esac

  mkdir -p /tmp/retailvision-tools
  cd /tmp/retailvision-tools

  if need terraform; then
    curl -fsSLo terraform.zip "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${bin_arch}.zip"
    unzip -o terraform.zip
    "${SUDO[@]}" install -m 0755 terraform /usr/local/bin/terraform
  fi

  if need helm; then
    curl -fsSLo helm.tgz "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${bin_arch}.tar.gz"
    tar -xzf helm.tgz
    "${SUDO[@]}" install -m 0755 "linux-${bin_arch}/helm" /usr/local/bin/helm
  fi

  if need kubectl; then
    curl -fsSLo kubectl "https://s3.us-west-2.amazonaws.com/amazon-eks/${KUBECTL_VERSION}/${KUBECTL_DATE}/bin/linux/${bin_arch}/kubectl"
    "${SUDO[@]}" install -m 0755 kubectl /usr/local/bin/kubectl
  fi
}

install_macos_tools() {
  if ! command -v brew >/dev/null 2>&1; then
    echo "ERROR: Homebrew is required on macOS. Install it from https://brew.sh, then rerun this script." >&2
    exit 1
  fi
  brew install awscli terraform kubectl helm jq make
}

case "$(uname -s)" in
  Linux)
    install_linux_packages
    install_linux_binaries
    ;;
  Darwin)
    install_macos_tools
    ;;
  *)
    echo "ERROR: unsupported OS: $(uname -s)" >&2
    exit 1
    ;;
esac

export PATH="/usr/local/bin:$PATH"
hash -r

for cmd in aws terraform kubectl helm jq curl git make; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: $cmd is still missing after installation." >&2
    exit 1
  fi
done

echo "Deployment tools ready:"
aws --version
terraform version | head -1
helm version --short
kubectl version --client
jq --version
