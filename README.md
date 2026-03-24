# Physical CI

Hardware-in-the-loop CI system that uses a robotic arm to physically press numpad buttons and verify the inputs, built with [Lingua Franca](https://www.lf-lang.org/) reactive programming.

## Architecture

```
GitHub Actions (self-hosted)
    └── Lingua Franca reactor
            ├── InputGenerator  → generates random key sequences
            ├── Robot           → WidowX arm presses the numpad button
            └── NumpadReceiver  → reads actual numpad input via evdev
```

The system compiles LF source (`src/*.lf`) to C extensions + Python wrappers, then executes the reactive test loop: generate key → press button → verify input → repeat.

## Hardware

| Component | Details |
|-----------|---------|
| WidowX arm (wxai_v0) | `192.168.1.2`, controlled via `trossen_arm` |
| USB numpad | `/dev/input/by-id/usb-Usb_KeyBoard_Usb_KeyBoard-event-kbd` |
| Raspberry Pi Pico W | `/dev/ttyACM0`, GPIO20 relay for robot power control |

## Setup

### Pico firmware

```bash
sudo chmod 666 /dev/ttyACM0
mpremote connect /dev/ttyACM0 cp pico/pico.py :main.py
mpremote connect /dev/ttyACM0 reset
```

### Calibration

Record numpad button positions (hover + press coordinates) for the arm:

```bash
python examples/record_positions.py   # saves to examples/positions.json
```

### Robot power control

```bash
python pico/serial_control.py on              # power on the robot
python pico/serial_control.py off             # power off
python pico/serial_control.py on --mode normally_on  # use normally-on relay mode
```

### Build & run

```bash
lfc-dev src/parallel.lf && ./bin/parallel
```

## CI/CD

**`ci.yml`** — Runs on PRs to `main` on a self-hosted runner with the physical hardware attached. Compiles and executes `src/parallel.lf`.

**`test.yml`** — Manual-dispatch workflow for [Actions Runner Controller](https://github.com/actions/actions-runner-controller) (Kubernetes-based runners).

### Docker image

```bash
docker build -t depetrol/lingua-franca .
docker push depetrol/lingua-franca
```

### ARC setup (k3s)

ARC runners must use **k3s** (not minikube). Minikube's Docker driver wraps the cluster in a container, so `hostNetwork: true` only exposes the minikube container's network — not the host LAN where the robot lives. k3s runs natively on the host, so `hostNetwork: true` gives pods direct access to the physical network.

The runner pod uses `hostNetwork: true` and `dnsPolicy: ClusterFirstWithHostNet` (configured in `arc-config.yaml`) to reach the robot at `192.168.1.2`. The robot IP is configurable via the `ROBOT_HOST` environment variable.

```bash
# Install ARC controller
helm install arc \
    --namespace "arc-controller" \
    --create-namespace \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller

# Deploy runner scale set
helm install "lf-thor-widowx" \
    --namespace "arc-runners" \
    --create-namespace \
    --set githubConfigSecret.github_token="$GITHUB_PAT" \
    --set maxRunners=1 \
    -f arc-config.yaml \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set

# Upgrade after config changes
helm upgrade "lf-thor-widowx" \
    --namespace "arc-runners" \
    --set githubConfigSecret.github_token="$GITHUB_PAT" \
    --set maxRunners=1 \
    -f arc-config.yaml \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set
```

### ARC shutdown

```bash
helm uninstall lf-thor-widowx --namespace arc-runners
helm uninstall arc --namespace arc-controller
```

### ARC status

```bash
kubectl get pods -n arc-controller     # controller + listener status
kubectl get pods -n arc-runners        # runner pods
kubectl logs -n arc-controller -l app.kubernetes.io/name=gha-runner-scale-set-controller  # controller logs
kubectl logs -n arc-runners -l actions.github.com/scale-set-name=lf-thor-widowx           # runner logs

# live logs of a currently running runner pod
kubectl get pods -n arc-runners                          # find the pod name
kubectl logs -f -n arc-runners <pod-name>                # follow logs
```

### Scheduling CI

To run CI automatically overnight (1 AM–5 AM PST), add crontab entries:

```bash
crontab -e

# Start CI at 2 AM PST
0 2 * * * cd /path/to/physical-ci && scripts/start_ci.sh >> ci.log 2>&1

# Stop CI at 4 AM PST
0 4 * * * cd /path/to/physical-ci && scripts/stop_ci.sh >> ci.log 2>&1
```

`GITHUB_PAT` must be set in your environment (e.g. in `~/.bashrc`). The system timezone must be set to `America/Los_Angeles` (`timedatectl set-timezone America/Los_Angeles`).

## Project structure

```
src/             Lingua Franca source (ci.lf, parallel.lf, robot.lf)
src-gen/         Generated C + Python code (gitignored)
bin/             Executable wrapper scripts (gitignored)
pico/            Pico W firmware & serial power control
examples/        Calibration tools, manual test utilities, positions.json
.github/         CI workflows
```
