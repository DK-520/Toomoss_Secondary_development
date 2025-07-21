import os
from PyQt5.QtCore import QThread, pyqtSignal
from UDS_OTA import UDS_OTA

class OTAWorker(QThread):
    """OTA升级工作线程"""
    update_progress = pyqtSignal(int)
    log_message = pyqtSignal(str, str)  # (message, level)
    finished = pyqtSignal(bool)

    def __init__(self, device_handle, can_channel, firmware_data):
        super().__init__()
        self.device = device_handle
        self.channel = can_channel
        self.firmware = firmware_data

    def run(self):
        def console_log(msg, level='info'):
            self.log_message.emit(msg, level)

        try:
            ota = UDS_OTA(self.device, self.channel, console_log)
            success = ota.perform_update(self.firmware)
            self.finished.emit(success)
        except Exception as e:
            self.log_message(f"OTA异常: {str(e)}", "error")
            self.finished.emit(False)