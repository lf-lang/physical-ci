#!/usr/bin/env python3
"""WebSocket server that reads numpad key presses and pushes them to all
connected subscribers.

Connect to ws://127.0.0.1:5100 to receive key presses as plain text messages.
"""

import asyncio
import os
import sys
import threading
from websockets.asyncio.server import serve

from evdev import InputDevice, categorize, ecodes

DEVICE_PATH = "/dev/input/by-id/usb-Usb_KeyBoard_Usb_KeyBoard-event-kbd"
PORT = 5100
# Loopback only: the simulation's numpad server listens on 127.0.0.2:5100 on the same host.
HOST = "127.0.0.1"

subscribers: set = set()
loop: asyncio.AbstractEventLoop = None


def numpad_reader():
    try:
        read_numpad()
    except OSError as e:
        # Exit the whole process rather than leave a server that never reports keys.
        print(f"Numpad {DEVICE_PATH} unavailable: {e}", file=sys.stderr)
        os._exit(1)


def read_numpad():
    device = InputDevice(DEVICE_PATH)
    device.grab()
    # clear buffer
    try:
        while device.read_one() is not None:
            pass
    except OSError:
        pass
    print(f"Numpad reader connected to: {device.name}")
    for event in device.read_loop():
        if event.type == ecodes.EV_KEY:
            key_event = categorize(event)
            if key_event.keystate == 1:  # Key Down
                key_name = key_event.keycode.split("KEY_KP")[1]
                print(f"Key pressed: {key_name}")
                loop.call_soon_threadsafe(asyncio.ensure_future, broadcast(key_name))


async def broadcast(key: str):
    if subscribers:
        await asyncio.gather(
            *(ws.send(key) for ws in subscribers),
            return_exceptions=True,
        )


async def handler(websocket):
    subscribers.add(websocket)
    print(f"[WS] +subscriber ({len(subscribers)} total)")
    try:
        async for _ in websocket:
            pass  # ignore incoming messages, just keep connection alive
    finally:
        subscribers.discard(websocket)
        print(f"[WS] -subscriber ({len(subscribers)} total)")


async def main():
    global loop
    loop = asyncio.get_running_loop()

    reader_thread = threading.Thread(target=numpad_reader, daemon=True)
    reader_thread.start()

    async with serve(handler, HOST, PORT):
        print(f"Numpad WS server listening on port {PORT}")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
