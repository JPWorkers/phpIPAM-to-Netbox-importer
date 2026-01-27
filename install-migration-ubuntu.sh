#!/usr/bin/env bash
#
# install-migration-ubuntu.sh
# Complete setup for phpIPAM → NetBox migration on Ubuntu
#

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   phpIPAM → NetBox Migration - Ubuntu Setup Script${NC}"
echo -e "${BLUE}══════════════════════════════════════════════════════════════${NC}\n"

# ────────────────────────────────────────────────
#  Step 1: Check Ubuntu Version
# ────────────────────────────────────────────────
echo -e "${YELLOW}[1/6]${NC} Checking Ubuntu version..."

if [[ -f /etc/os-release ]]; then
    source /etc/os-release
    echo "       OS: ${PRETTY_NAME}"
    
    # Extract major version
    UBUNTU_VERSION=$(echo "$VERSION_ID" | cut -d. -f1)
    
    if [[ "$UBUNTU_VERSION" -lt 22 ]]; then
        echo -e "${RED}Error: Ubuntu 22.04+ required. You have ${VERSION_ID}${NC}"
        echo "       Ubuntu 20.04's Python 3.8 is too old for NetBox 4.5+"
        exit 1
    fi
else
    echo -e "${YELLOW}Warning: Cannot detect OS version, proceeding anyway...${NC}"
fi

# ────────────────────────────────────────────────
#  Step 2: Install System Dependencies
# ────────────────────────────────────────────────
echo -e "\n${YELLOW}[2/6]${NC} Installing system dependencies..."

sudo apt update -qq
sudo apt install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    ca-certificates

echo -e "       ${GREEN}✓ System packages installed${NC}"

# ────────────────────────────────────────────────
#  Step 3: Verify Python Version
# ────────────────────────────────────────────────
echo -e "\n${YELLOW}[3/6]${NC} Verifying Python version..."

PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

echo "       Python version: ${PYTHON_VERSION}"

if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 10 ]]; then
    echo -e "${RED}Error: Python 3.10+ required for NetBox 4.5+${NC}"
    exit 1
fi

echo -e "       ${GREEN}✓ Python version OK${NC}"

# ────────────────────────────────────────────────
#  Step 4: Create Virtual Environment
# ────────────────────────────────────────────────
echo -e "\n${YELLOW}[4/6]${NC} Setting up virtual environment..."

VENV_DIR="./venv"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE}")" && pwd)"

cd "$SCRIPT_DIR"

if [[ -d "$VENV_DIR" ]]; then
    echo "       Existing venv found, removing..."
    rm -rf "$VENV_DIR"
fi

python3 -m venv "$VENV_DIR"
echo -e "       ${GREEN}✓ Virtual environment created${NC}"

# ────────────────────────────────────────────────
#  Step 5: Install Python Packages
# ────────────────────────────────────────────────
echo -e "\n${YELLOW}[5/6]${NC} Installing Python packages..."

# Activate venv
source "${VENV_DIR}/bin/activate"

# Upgrade pip first
pip install --upgrade pip setuptools wheel -q

# Install required packages
pip install \
    "pynetbox>=7.4.0" \
    "requests>=2.31.0" \
    "python-slugify>=8.0.0"

echo -e "       ${GREEN}✓ Python packages installed${NC}"

# ────────────────────────────────────────────────
#  Step 6: Verify Installation
# ────────────────────────────────────────────────
echo -e "\n${YELLOW}[6/6]${NC} Verifying installation..."

# Test imports
python3 << 'PYTEST'
import sys
try:
    import pynetbox
    import requests
    from slugify import slugify
    print(f"       pynetbox version: {pynetbox.__version__}")
    print(f"       requests version: {requests.__version__}")
    print("       slugify: OK")
    sys.exit(0)
except ImportError as e:
    print(f"       Import error: {e}")
    sys.exit(1)
PYTEST

if [[ $? -eq 0 ]]; then
    echo -e "       ${GREEN}✓ All packages verified${NC}"
else
    echo -e "       ${RED}✗ Package verification failed${NC}"
    exit 1
fi

# Deactivate venv
deactivate

# ────────────────────────────────────────────────
#  Done - Print Summary
# ────────────────────────────────────────────────
echo -e "\n${BLUE}══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}                    Setup Complete!${NC}"
echo -e "${BLUE}══════════════════════════════════════════════════════════════${NC}"

cat << EOF

Environment Summary:
  • Ubuntu:     ${PRETTY_NAME:-Unknown}
  • Python:     ${PYTHON_VERSION}
  • Venv:       ${SCRIPT_DIR}/${VENV_DIR}

Next Steps:

  1. Activate the virtual environment:
     ${YELLOW}source ./venv/bin/activate${NC}

  2. Set your API tokens:
     ${YELLOW}export PHPIPAM_TOKEN="your_phpipam_api_token"${NC}
     ${YELLOW}export NETBOX_TOKEN="your_netbox_api_token"${NC}

  3. Edit the migration script with your URLs:
     ${YELLOW}nano migrate_phpipam_to_netbox.py${NC}

  4. Run in dry-run mode first:
     ${YELLOW}python3 migrate_phpipam_to_netbox.py${NC}

  5. When done:
     ${YELLOW}deactivate${NC}

EOF
