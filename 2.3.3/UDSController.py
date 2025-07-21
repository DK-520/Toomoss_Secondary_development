# UDSController.py
from CANController import *
from Crypto.Hash import CMAC
from Crypto.Cipher import AES
from PyQt5.QtCore import QThread, pyqtSignal, QObject, QMutex, QWaitCondition

KEY_CMAC = bytes([0xF9,0xA7,0xBE,0xB7,0xE3,0x46,0x15,0xB0,0xE2,0xD9,0xF3,0xE3,0x07,0xF2,0xCD,0x93])


class UDSRequestWorker(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progressed = pyqtSignal(int)  # 新增信号

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.mutex = QMutex()
        self.wait_condition = QWaitCondition()
        self.abort = False

    def run(self):
        try:
            if hasattr(self.func, '__name__') and self.func.__name__ in ['firmware_update', 'start_ota_update']:
                result = self.func(*self.args, **self.kwargs, progress_callback=self.progressed.emit)
            else:
                result = self.func(*self.args, **self.kwargs)
            if not self.abort:
                self.finished.emit(result)
        except Exception as e:
            if not self.abort:
                self.error.emit(str(e))

    def stop(self):
        self.mutex.lock()
        self.abort = True
        self.wait_condition.wakeOne()
        self.mutex.unlock()

class UDSController:
    def __init__(self, console: UDSConsole):
        self.console = console
        self.usb_handler = USBHandler(console)
        self.can_controller = CANController(console)
        self.connected = False
        self.last_seed = None
        self.worker_thread = None
        self.worker = None
        self.state = type('State', (), {})()  # 动态创建一个 state 对象

    def connect_device(self):
        """
        连接设备并初始化 CAN 接收器
        """
        try:
            ret, handles = self.usb_handler.scan_devices()
            if ret > 0:
                self.console.log(f"发现 {ret} 台设备")
                if self.usb_handler.open_device():

                    self.connected = True
                    return True
                else:
                    self.console.log("设备连接失败")
            else:
                self.console.error("未检测到设备")
                return False
        except Exception as e:
            self.console.error(f"连接设备时发生异常: {str(e)}")
            return False

    def disconnect_device(self):
        """
        断开设备连接并停止 CAN 接收器
        """
        try:
            if self.connected:
                self.usb_handler.close_device()
                self.connected = False
                return True
            else:
                self.console.log("设备未连接")
                return False
        except Exception as e:
            self.console.error(f"断开设备时发生异常: {str(e)}")
            return False

    def set_session(self, session_type):
        send_diagnostic_session_control(self.usb_handler.DevHandles[0], self.can_controller.CANChannel, session_type)
        print("正在发送诊断会话控制请求...")
        print(f"目标会话类型: {session_type:02X}")

    def request_seed(self, level):
        seed = request_security_access(self.usb_handler.DevHandles[0], self.can_controller.CANChannel, level=0x11)
        if seed:
            self.state.last_seed = seed  # ← 保存种子
            self.console.log("种子请求成功")
        else:
            self.console.log("种子请求失败")
        return seed

    def verify_key(self, key):
        """验证安全密钥"""
        if not self.state.last_seed:
            self.console.log("错误：没有可用的种子数据")
            return False

        try:
            cobj = CMAC.new(KEY_CMAC, ciphermod=AES)
            cobj.update(bytes(self.state.last_seed))
            expected_key = cobj.digest()[:8]  # 取前8字节

            self.console.log(f"预期密钥: {expected_key.hex()}")
            self.console.log(f"传入密钥: {bytes(key).hex()}")

            return key == expected_key
        except Exception as e:
            self.console.log(f"密钥验证异常: {str(e)}")
            return False

    def send_key(self, level, key):
        result = send_security_key(self.usb_handler.DevHandles[0], self.can_controller.CANChannel, level, key)

        if result:
            if self.verify_key(key):  # ← 调用验证函数
                self.console.log("密钥验证成功")
            else:
                self.console.log("密钥验证失败")
        else:
            self.console.log("发送密钥失败")
        return result

    def firmware_update(self, data_block, progress_callback=None):
        total_blocks = (len(data_block) + 6) // 7
        block_index = 0
        memory_address = 0x00080000

        if request_download(self.usb_handler.DevHandles[0], self.can_controller.CANChannel,
                            memory_address=memory_address, length=len(data_block)):
            while block_index * 7 < len(data_block):
                start = block_index * 7
                end = min(start + 7, len(data_block))
                current_block = data_block[start:end]
                transfer_data(self.usb_handler.DevHandles[0], self.can_controller.CANChannel, block_index + 1, current_block)
                block_index += 1
                if progress_callback:
                    progress_callback(int(block_index / total_blocks * 100))
            request_transfer_exit(self.usb_handler.DevHandles[0], self.can_controller.CANChannel)
            return True
        return False

    def enter_programming_mode(self, progress_callback=None):
        def on_result(result):
            if result:
                self.console.log("进入编程会话成功")
            else:
                self.console.log("进入编程会话失败")

        self._run_in_worker(
            send_diagnostic_session_control,
            on_result,
            progress_callback,  # 传递进度回调
            self.usb_handler.DevHandles[0],
            self.can_controller.CANChannel,
            session_type=0x02
        )

    def stop_all_requests(self):
        if self.worker:
            self.worker.stop()
            # 等待线程结束，最多等待2秒
            if self.worker_thread and self.worker_thread.isRunning():
                self.worker_thread.quit()
                if not self.worker_thread.wait(2000):  # 等待2秒
                    self.worker_thread.terminate()  # 强制终止
