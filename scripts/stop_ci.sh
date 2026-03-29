#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

set -a
source "$SCRIPT_DIR/.env"
set +a

echo "Setting max runners to 0..."
helm upgrade "lf-thor-widowx" \
    --namespace "arc-runners" \
    --set githubConfigSecret.github_token="$GITHUB_PAT" \
    --set minRunners=0 \
    --set maxRunners=0 \
    -f "$SCRIPT_DIR/arc-config.yaml" \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set

echo "Powering off robot..."
python3 "$SCRIPT_DIR/pico/serial_control.py" off

sleep 2

echo "CI stopped."
