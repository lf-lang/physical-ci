# Physical CI

Hardware-in-the-loop CI system that uses a robotic arm to physically press numpad buttons and verify the inputs, built with [Lingua Franca](https://www.lf-lang.org/) reactive programming.

## Architecture

```
GitHub Actions (self-hosted)
    └── Lingua Franca reactor
            ├── InputGenerator  → generates random key sequences
            ├── Robot           → WidowX arm presses the numpad button
            └── NumpadReceiver  → subscribes to numpad_server.py for the actual key press
```

The system compiles LF source (`src/*.lf`) to C extensions + Python wrappers, then executes the reactive test loop: generate key → press button → verify input → repeat.

## Hardware


| Component            | Details                                                    |
| -------------------- | ---------------------------------------------------------- |
| WidowX arm (wxai_v0) | `192.168.1.2`, controlled via `trossen_arm`                |
| USB numpad           | `/dev/input/by-id/usb-Usb_KeyBoard_Usb_KeyBoard-event-kbd` |
| Raspberry Pi Pico W  | `/dev/ttyACM0`, GPIO20 relay for robot power control       |




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



## Simulation

[trossen_arm_sim](https://github.com/depetrol/trossen_arm_sim) replaces the arm controller with a MuJoCo simulation that the unmodified `trossen_arm` driver connects to; see its README for usage, scenes and the collision stream. Here it is used with `examples/scene_numpad.xml`, which places the numpad to match `examples/positions.json`, and the program is pointed at it by setting `ROBOT_HOST` to `127.0.0.1`.

```bash
pip install trossen_arm_sim
trossen-arm-sim examples/scene_numpad.xml            # terminal 1
python examples/press_button.py --sim                # terminal 2; omit --sim for the real robot
```



## CI/CD

`ci.yml` — Manual-dispatch pipeline that compiles `src/parallel.lf` and runs the binary in two stages, as two jobs with identical steps. The program only knows the arm at `ROBOT_HOST` and the numpad server at `NUMPAD_SERVER_HOST`, set per runner in its job template (`arc-job-template*.yaml`); whether those are real or simulated is decided outside the container.

1. `simulate` — runs against `simulation/simulation.py`, which serves the simulated arm, a simulated numpad server that reports a key whenever the simulated gripper touches it, and collision detection: if the arm touches anything but a key, or presses a key harder than 10 N (`--max-press-force`), the simulated controller faults. The driver in the program then raises, the program exits non-zero and the job fails, exactly as a hardware fault would. The reason is in the simulator's log.
2. `execute` (only after stage 1 passes) — passes if the program exits cleanly, i.e. every key the robot pressed was verified through the numpad server. For now it runs against the same simulation; it moves to the `lf-thor-widowx` runner (`arc-job-template.yaml`, real arm and `numpad_server.py`) once it should drive the real robot.

Both jobs run on the `mymac` runner (kind under Docker Desktop, `arc-job-template-sim.yaml`), whose pods reach the Mac at `192.168.65.254`. Serve the simulation there before dispatching:

```bash
python simulation/simulation.py            # headless
mjpython simulation/simulation.py --viewer # with the MuJoCo viewer
```

To run the program locally against it:

```bash
lfc-dev src/parallel.lf
ROBOT_HOST=127.0.0.1 NUMPAD_SERVER_HOST=127.0.0.1 ./bin/parallel
```

`collide.yml` — Manual-dispatch check of the collision detection itself. Runs `src/collide.lf`, which drives the gripper into the floor, on the simulation runner; the job fails when the simulation faults the controller on the collision.

`lf-pr.yml` — Reusable workflow that tests a lingua-franca pull request on this hardware. lingua-franca's `physical-ci.yml` calls it when a pull request is labeled `physical-ci`, and again on each new commit while the label is present. It runs in lingua-franca's context: `build-lfc` checks out the pull request's merge commit, builds `lfc` with `./gradlew :cli:lfc:installDist`, and uploads it as the `lfc` artifact. `simulate` and `execute` install that `lfc` into the job image and run the same steps as `ci.yml`, so results appear as checks on the pull request.

### Testing lingua-franca pull requests

These settings make the cross-repository call possible and gate runs from pull requests:

- **physical-ci is public.** A public repository such as lingua-franca can only call reusable workflows from public repositories.
- **lingua-franca and physical-ci each have a `physical-ci` environment with required reviewers.** `build-lfc` uses it, so a maintainer approves every run of `lf-pr.yml` before code from the pull request is built or run. Create both before `physical-ci.yml` lands: GitHub creates a missing environment without protection.
- **lingua-franca requires approval to run workflows from all external contributors.** The runners are in the organization's Default group, which every lf-lang repository can use, so a pull request from a fork could add its own job with `runs-on: mymac`. This approval setting is what stops such a job from running unreviewed.
- **lingua-franca has a `physical-ci` label.**

`test.yml` — Manual-dispatch workflow for [Actions Runner Controller](https://github.com/actions/actions-runner-controller) (Kubernetes-based runners).

### Job image

Every job names its image in the workflow's `container:` key. The runners use ARC's kubernetes mode: the runner pod runs only the GitHub runner, and for each job it starts a separate pod from that image. The runner's job template (`arc-job-template*.yaml`) adds host networking and the `ROBOT_HOST` and `NUMPAD_SERVER_HOST` env to that pod; it cannot change the image.

To use another image, change `container.image` in the workflow. The image needs `bash`, Java 17 or newer, and the program's Python packages, plus `lfc` on its `PATH` for `ci.yml` and `collide.yml` (`lf-pr.yml` brings its own `lfc`), and the cluster must be able to pull it: push it to a registry, or on mymac load a local build into kind.

```bash
docker build -t depetrol/lingua-franca .
docker push depetrol/lingua-franca
kind load docker-image depetrol/lingua-franca --name arc   # mymac only, for an image that is not pushed
```



### ARC setup (k3s)

ARC runners must use **k3s** (not minikube). Minikube's Docker driver wraps the cluster in a container, so `hostNetwork: true` only exposes the minikube container's network — not the host LAN where the robot lives. k3s runs natively on the host, so `hostNetwork: true` gives pods direct access to the physical network.

The job pod uses `hostNetwork: true` and `dnsPolicy: ClusterFirstWithHostNet` (configured in `arc-job-template.yaml`) to reach the robot at `192.168.1.2`. The robot IP is configurable via the `ROBOT_HOST` environment variable.

The commands below are for the robot host. On mymac, run them against a kind cluster (`kind create cluster --name arc`) with the release name `mymac` and `arc-job-template-sim.yaml`. Both hosts share `arc-config.yaml`; its work volume uses the cluster's default storage class (`standard` on kind, `local-path` on k3s). A runner set installed without kubernetes mode is switched by `helm uninstall` and `helm install`, not `helm upgrade`.

Runners register to the `lf-lang` organization in its Default runner group. ARC authenticates as the LF-ACT-App GitHub App, which has the organization permission "Self-hosted runners: Read and write". Its credentials are in the `lf-arc-github-app` secret in the `arc-runners` namespace.

```bash
# Start Kind (macOS)
kind create cluster --name arc 
# Install ARC controller
helm install arc \
    --namespace "arc-controller" \
    --create-namespace \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller

# Job pod template, mounted by the runner pods
kubectl create namespace arc-runners
kubectl apply -f arc-job-template.yaml

# GitHub App credentials
kubectl create secret generic lf-arc-github-app -n arc-runners \
    --from-literal=github_app_id=5203721 \
    --from-literal=github_app_installation_id=168636877 \
    --from-file=github_app_private_key=/path/to/lf-act-app.private-key.pem

# Deploy runner scale set
helm install "lf-thor-widowx" \
    --namespace "arc-runners" \
    --set maxRunners=1 \
    -f arc-config.yaml \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set

# Upgrade after config changes
kubectl apply -f arc-job-template.yaml
helm upgrade "lf-thor-widowx" \
    --namespace "arc-runners" \
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
kubectl get pods -n arc-runners        # runner pods, and a <runner-pod>-workflow pod per running job
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

The system timezone must be set to `America/Los_Angeles` (`timedatectl set-timezone America/Los_Angeles`).

## Project structure

```
src/             Lingua Franca source (ci.lf, parallel.lf, robot.lf)
src-gen/         Generated C + Python code (gitignored)
bin/             Executable wrapper scripts (gitignored)
pico/            Pico W firmware & serial power control
examples/        Calibration tools, manual test utilities, positions.json
simulation/      Simulated arm and numpad endpoints with collision detection, for CI
.github/         CI workflows
```

