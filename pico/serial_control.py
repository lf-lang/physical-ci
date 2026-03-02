import serial
import time

class SerialControl:
    def __init__(self, port='/dev/ttyACM0', baudrate=115200, timeout=2):
        self.ser = serial.Serial(port, baudrate, timeout=timeout)
    def GPIO_ON(self):
        self.ser.write(b'1')
    def GPIO_OFF(self):
        self.ser.write(b'0')
    def close(self):
        self.ser.close()

if __name__ == "__main__":
    ser = SerialControl()
    ser.GPIO_ON()
    time.sleep(2)
    ser.GPIO_OFF()
    ser.close()