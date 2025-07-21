
from UDS_service import *
from UDSConsole import *


class USBHandler:
    def __init__(self, console: UDSConsole):
        self.DevHandles = (c_uint * 20)()
        self.console = console
        self.connected = False

    def scan_devices(self):
        ret = USB_ScanDevice(byref(self.DevHandles))
        return ret, self.DevHandles

    def open_device(self):
        if self.DevHandles[0]:
            ret = USB_OpenDevice(self.DevHandles[0])
            self.connected = bool(ret)
            if self.connected:
                self.console.info("设备打开成功")
            else:
                self.console.error("设备打开失败")
            return self.connected
        return False

    def close_device(self):
        if self.DevHandles[0]:
            ret = USB_CloseDevice(self.DevHandles[0])
            self.connected = not bool(ret)
            if not self.connected:
                self.console.info("设备关闭成功")
            else:
                self.console.error("设备关闭失败")
            return self.connected
        return False

