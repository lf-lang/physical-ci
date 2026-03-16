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

### ARC setup

```bash
helm install arc \
    --namespace "arc-systems" \
    --create-namespace \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller

helm install "arc-runner-set" \
    --namespace "arc-runners" \
    --create-namespace \
    --set githubConfigUrl="https://github.com/depetrol/physical-ci" \
    --set githubConfigSecret.github_token="${GITHUB_PAT}" \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set
```

## Project structure

```
src/             Lingua Franca source (ci.lf, parallel.lf, robot.lf)
src-gen/         Generated C + Python code (gitignored)
bin/             Executable wrapper scripts (gitignored)
pico/            Pico W firmware & serial power control
examples/        Calibration tools, manual test utilities, positions.json
.github/         CI workflows
```
