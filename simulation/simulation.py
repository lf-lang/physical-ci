"""Simulated arm and numpad endpoints, run on the machine that CI reaches as
ROBOT_HOST and NUMPAD_SERVER_HOST.

Starts trossen_arm_sim with the numpad scene (arm controller on TCP 50001
and UDP 50000, collision stream on 50002), a numpad server on port 5100 that
speaks the protocol of numpad_server.py and reports a key whenever the
simulated gripper touches it, and collision detection that faults the
simulated controller when the arm touches anything but a key. The CI
program runs against these endpoints as if they were the real arm and
numpad: a collision surfaces in the program as a driver error, exactly as a
hardware fault would.

    python simulation/simulation.py                # headless
    mjpython simulation/simulation.py --viewer     # with the MuJoCo viewer (macOS)
"""

import argparse
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from trossen_arm_sim.collision import CollisionMonitor
from trossen_arm_sim.collision_server import CollisionWebSocketServer
from trossen_arm_sim.protocol import ErrorState
from trossen_arm_sim.server import TrossenArmSimServer
from trossen_arm_sim.sim import WidowXSim

ROOT = Path(__file__).resolve().parent.parent
NUMPAD_PORT = 5100  # same port as numpad_server.py

ARM_LABEL_PREFIXES = ("base_link", "link_", "carriage_")
FINGERS = {"carriage_left", "carriage_right"}
# key_* geom name in the scene -> key name emitted by numpad_server.py
# (the suffix of the evdev KEY_KP* keycode); digits map to themselves.
KEY_NAMES = {"enter": "ENTER", "plus": "PLUS", "-": "MINUS", "slash": "SLASH",
             "star": "ASTERISK", "dot": "DOT"}


def pressed_key(event: dict) -> str | None:
    """Key name if the contact event is a gripper finger touching a key geom."""
    if event["geom1"] in FINGERS and event["geom2"].startswith("key_"):
        name = event["geom2"][len("key_"):]
        return KEY_NAMES.get(name, name)
    return None


class ContactListener(threading.Thread):
    """Runs on_contact for every begin/end event of the collision monitor."""

    def __init__(self, monitor: CollisionMonitor, name: str):
        super().__init__(daemon=True, name=name)
        self._monitor = monitor

    def run(self) -> None:
        _, events = self._monitor.subscribe()
        while True:
            self.on_contact(events.get().to_dict())

    def on_contact(self, event: dict) -> None:
        raise NotImplementedError


class _NumpadHandler(BaseHTTPRequestHandler):
    """Protocol of numpad_server.py: GET /key blocks until a key is pressed and
    returns its name; GET /clear discards buffered presses."""

    def do_GET(self) -> None:
        numpad: SimulatedNumpad = self.server.numpad
        if self.path == "/key":
            body = numpad.next_key()
            if body is None:
                return  # superseded by a newer request; this client is gone
        elif self.path == "/clear":
            numpad.clear()
            body = "cleared"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, format: str, *args) -> None:
        logging.getLogger("numpad").debug("%s", args[0])


class SimulatedNumpad(ContactListener):
    """Stand-in for numpad_server.py: a key counts as pressed when the first
    gripper finger touches its geom, and can be pressed again once both
    fingers have left it.

    Only the newest /key request is served. A program that dies while
    waiting on /key leaves its request behind; the next program's /clear or
    /key supersedes it, so the stale request cannot swallow a key press.
    """

    def __init__(self, monitor: CollisionMonitor, host: str):
        super().__init__(monitor, "numpad")
        self._log = logging.getLogger("numpad")
        self._keys: list[str] = []
        self._generation = 0  # bumped by every /key and /clear
        self._presses = threading.Condition()
        self._touching: dict[str, set[str]] = {}
        self._server = ThreadingHTTPServer((host, NUMPAD_PORT), _NumpadHandler)
        self._server.daemon_threads = True
        self._server.numpad = self
        self._http = threading.Thread(target=self._server.serve_forever,
                                      daemon=True, name="numpad-http")

    def start(self) -> None:
        super().start()
        self._http.start()
        self._log.info("Listening on port %d", NUMPAD_PORT)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def on_contact(self, event: dict) -> None:
        key = pressed_key(event)
        if key is None:
            return
        fingers = self._touching.setdefault(key, set())
        if event["type"] == "begin":
            if not fingers:
                self._log.info("Key pressed: %s", key)
                with self._presses:
                    self._keys.append(key)
                    self._presses.notify_all()
            fingers.add(event["geom1"])
        else:
            fingers.discard(event["geom1"])

    def next_key(self) -> str | None:
        """Discard buffered presses and wait for the next one; None if a newer
        request superseded this one meanwhile."""
        with self._presses:
            generation = self.clear()
            while not self._keys and self._generation == generation:
                self._presses.wait()
            return self._keys.pop(0) if self._generation == generation else None

    def clear(self) -> int:
        with self._presses:
            self._keys.clear()
            self._generation += 1
            self._presses.notify_all()
            return self._generation


class CollisionDetection(ContactListener):
    """Faults the simulated controller on any contact that is not a gripper
    finger pressing a key, or a press harder than max_press_force."""

    def __init__(self, monitor: CollisionMonitor, arm: TrossenArmSimServer,
                 max_press_force: float):
        super().__init__(monitor, "collision-detection")
        self._log = logging.getLogger("collision")
        self._arm = arm
        self._max_press_force = max_press_force

    def stop(self) -> None:
        pass

    def on_contact(self, event: dict) -> None:
        if not event["body1"].startswith(ARM_LABEL_PREFIXES) \
                or {event["geom1"], event["geom2"]} == FINGERS:
            return  # scene objects touching each other, or the gripper closing
        pair = f"{event['geom1']} ({event['body1']}) -> {event['geom2']} ({event['body2']})"
        if pressed_key(event) is not None:
            if event["type"] == "end":
                self._log.info("Press: %s, %.2f N peak for %.2f s",
                               pair, event["peak_force"], event["duration"])
                if event["peak_force"] > self._max_press_force:
                    self._fault(f"{pair} pressed with {event['peak_force']:.1f} N "
                                f"(limit {self._max_press_force:.0f} N)")
        elif event["type"] == "begin":
            self._fault(f"{pair} hit with {event['force']:.1f} N")

    def _fault(self, description: str) -> None:
        if self._arm.error_state != ErrorState.NONE:
            return  # already faulted; the arm may keep touching things while it stops
        self._arm.fault(ErrorState.JOINT_DISABLED_UNEXPECTEDLY,
                        f"collision at {self._monitor.time:.3f}s: {description}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scene", nargs="?", default=str(ROOT / "examples" / "scene_numpad.xml"),
                        help="MuJoCo scene (default: examples/scene_numpad.xml)")
    parser.add_argument("--host", default="0.0.0.0", help="bind address")
    parser.add_argument("--viewer", action="store_true",
                        help="show the MuJoCo viewer (macOS: run with mjpython)")
    parser.add_argument("--max-press-force", type=float, default=10.0,
                        help="largest peak force [N] a key press may reach (a normal press is about 1 N)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s: %(message)s")

    sim = WidowXSim(args.scene)
    monitor = CollisionMonitor(sim)
    sim.start()
    arm = TrossenArmSimServer(sim, host=args.host)
    services = [
        arm,
        CollisionWebSocketServer(monitor, host=args.host),
        SimulatedNumpad(monitor, args.host),
        CollisionDetection(monitor, arm, args.max_press_force),
    ]
    for service in services:
        service.start()
    try:
        if args.viewer:
            sim.sync_viewer_loop()
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for service in reversed(services):
            service.stop()
        sim.stop()


if __name__ == "__main__":
    main()
