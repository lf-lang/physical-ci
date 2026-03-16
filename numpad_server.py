#!/usr/bin/env python3
"""HTTP server that reads numpad key presses and serves them via GET /key.

GET /key blocks until a key is pressed, then returns the key value as plain text.
GET /clear clears any buffered key presses.
"""

import threading
import queue
from http.server import HTTPServer, BaseHTTPRequestHandler
from evdev import InputDevice, categorize, ecodes

DEVICE_PATH = "/dev/input/by-id/usb-Usb_KeyBoard_Usb_KeyBoard-event-kbd"
PORT = 5100

key_queue = queue.Queue()


def numpad_reader():
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
                key_queue.put(key_name)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/key":
            # Block until a key is pressed
            key = key_queue.get()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(key.encode())
        elif self.path == "/clear":
            while not key_queue.empty():
                try:
                    key_queue.get_nowait()
                except queue.Empty:
                    break
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"cleared")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        print(f"[HTTP] {args[0]}")


if __name__ == "__main__":
    reader_thread = threading.Thread(target=numpad_reader, daemon=True)
    reader_thread.start()
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Numpad server listening on port {PORT}")
    server.serve_forever()
