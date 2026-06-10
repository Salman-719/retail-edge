#!/usr/bin/env bash
set -euo pipefail

report_error() {
  local status="$?"
  local line="$1"
  local command="$2"
  trap - ERR
  echo "ERROR: ${BASH_SOURCE[0]}:${line}: command failed with exit ${status}: ${command}" >&2
  exit "$status"
}
trap 'report_error "$LINENO" "$BASH_COMMAND"' ERR

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
  local packages=()
  local os_id=""

  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    os_id="${ID:-}"
  fi

  need unzip && packages+=(unzip)
  need tar && packages+=(tar)
  need gzip && packages+=(gzip)
  need git && packages+=(git)
  need jq && packages+=(jq)
  need make && packages+=(make)

  # Amazon Linux ships curl-minimal. Requesting the full curl package conflicts
  # with it, so never touch curl when the command already exists.
  if need curl; then
    if [[ "$os_id" == "amzn" ]]; then
      packages+=(curl-minimal)
    else
      packages+=(curl)
    fi
  fi

  if ((${#packages[@]} == 0)); then
    echo "Base Linux packages already installed."
    return
  fi

  echo "Installing missing base packages: ${packages[*]}"
  if command -v dnf >/dev/null 2>&1; then
    "${SUDO[@]}" dnf install -y --setopt=install_weak_deps=False "${packages[@]}"
  elif command -v yum >/dev/null 2>&1; then
    "${SUDO[@]}" yum install -y "${packages[@]}"
  elif command -v apt-get >/dev/null 2>&1; then
    "${SUDO[@]}" apt-get update
    "${SUDO[@]}" apt-get install -y --no-install-recommends "${packages[@]}"
  else
    echo "ERROR: no supported Linux package manager found." >&2
    echo "Install these commands manually: ${packages[*]}" >&2
    exit 1
  fi
}

install_linux_binaries() {
  local machine bin_arch aws_arch
  machine="$(uname -m)"
  case "$machine" in
    x86_64)
      bin_arch="amd64"
      aws_arch="x86_64"
      ;;
    aarch64|arm64)
      bin_arch="arm64"
      aws_arch="aarch64"
      ;;
    *)
      echo "ERROR: unsupported Linux architecture: $machine" >&2
      exit 1
      ;;
  esac

  mkdir -p /tmp/retailvision-tools
  cd /tmp/retailvision-tools

  if need aws; then
    echo "Installing AWS CLI v2 for ${aws_arch}..."
    rm -rf aws awscliv2.zip
    curl -fsSLo awscliv2.zip "https://awscli.amazonaws.com/awscli-exe-linux-${aws_arch}.zip"
    unzip -q awscliv2.zip
    "${SUDO[@]}" ./aws/install --update
  fi

  if need terraform; then
    echo "Installing Terraform ${TERRAFORM_VERSION} for ${bin_arch}..."
    rm -f terraform terraform.zip
    curl -fsSLo terraform.zip "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${bin_arch}.zip"
    unzip -oq terraform.zip
    "${SUDO[@]}" install -m 0755 terraform /usr/local/bin/terraform
  fi

  if need helm; then
    echo "Installing Helm ${HELM_VERSION} for ${bin_arch}..."
    rm -rf "linux-${bin_arch}" helm.tgz
    curl -fsSLo helm.tgz "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${bin_arch}.tar.gz"
    tar -xzf helm.tgz
    "${SUDO[@]}" install -m 0755 "linux-${bin_arch}/helm" /usr/local/bin/helm
  fi

  if need kubectl; then
    echo "Installing kubectl ${KUBECTL_VERSION} for ${bin_arch}..."
    rm -f kubectl
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
terraform version | sed -n '1p'
helm version --short
kubectl version --client
jq --version
