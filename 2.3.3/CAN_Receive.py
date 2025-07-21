# can_receiver.py
from PyQt5.QtCore import QThread, pyqtSignal
from time import sleep
from ctypes import byref
from usb2can import CAN_MSG

class CANReceiver(QThread):
    message_received = pyqtSignal(object)  # 接收的消息对象

    def __init__(self, device_handle, can_channel, msg_type, parent=None):
        import threading
        self.lock = threading.Lock()
        super().__init__(parent)
        self.device_handle = device_handle
        self.can_channel = can_channel
        self.msg_type = msg_type
        self.running = True

    def stop(self):
        self.running = False

    def run(self):
        from usb2can import CAN_GetMsg, CAN_MSG
        while self.running:
            CanMsgBuffer = (self.msg_type * 1024)()
            CanNum = CAN_GetMsg(self.device_handle, self.can_channel, byref(CanMsgBuffer))
            if CanNum > 0:
                for i in range(CanNum):
                    with self.lock:
                        self.message_received.emit(CanMsgBuffer[i])
            # 移除延迟以提高实时性
    