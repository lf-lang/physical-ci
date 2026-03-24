#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "Powering on robot..."
python3 "$SCRIPT_DIR/pico/serial_control.py" on

sleep 5

echo "Setting max runners to 1..."
helm upgrade "lf-thor-widowx" \
    --namespace "arc-runners" \
    --set githubConfigSecret.github_token="$GITHUB_PAT" \
    --set minRunners=1 \
    --set maxRunners=1 \
    -f "$SCRIPT_DIR/arc-config.yaml" \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set

echo "CI started."
