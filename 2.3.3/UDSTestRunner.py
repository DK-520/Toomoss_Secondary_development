from PyQt5.QtCore import QThread, pyqtSignal
from UDSController import UDSController


class UDSTestRunner(QThread):
    log_signal = pyqtSignal(str)        # 用于日志输出
    finished_signal = pyqtSignal()     # 测试完成时触发
    progress_signal = pyqtSignal(int)  # 用于更新进度条

    def __init__(self, controller: UDSController):
        super().__init__()
        self.controller = controller
        self.running = False
        self.repeat_count = 1          # 默认执行一轮
        self.current_round = 0         # 当前轮次
        self.total_steps = 5           # 单轮测试中的步骤总数

    def set_repeat(self, count: int):
        """
        设置测试重复次数
        :param count: -1 表示无限循环
        """
        self.repeat_count = count

    def stop(self):
        """
        停止当前测试流程
        """
        self.running = False

    def run(self):
        self.running = True
        self.current_round = 0

        try:
            while self.running and (self.repeat_count == -1 or self.current_round < self.repeat_count):
                self.current_round += 1
                step = 0
                self.log_signal.emit(f"【自动化测试】第 {self.current_round} 轮测试开始...")

                if not self.controller.connected:
                    self.log_signal.emit("【自动化测试】错误：未连接设备，请先连接。")
                    break

                # Step 1: 切换到默认会话
                if self.running:
                    self.log_signal.emit("【自动化测试】切换到默认会话...")
                    self.controller.set_session(0x01)
                    if not self.running:
                        break
                    step += 1
                    self.progress_signal.emit(int(step / self.total_steps * 100))
                else:
                    break

                # Step 2: 切换到扩展会话
                if self.running:
                    self.log_signal.emit("【自动化测试】切换到扩展会话...")
                    self.controller.set_session(0x03)
                    if not self.running:
                        break
                    step += 1
                    self.progress_signal.emit(int(step / self.total_steps * 100))
                else:
                    break

                # Step 3: 读取 ECU 版本号
                if self.running:
                    self.log_signal.emit("【自动化测试】读取ECU版本号...")
                    self.controller.read_version()
                    if not self.running:
                        break
                    step += 1
                    self.progress_signal.emit(int(step / self.total_steps * 100))
                else:
                    break

                # Step 4: 读取 DID F190
                if self.running:
                    self.log_signal.emit("【自动化测试】读取DID F190...")
                    self.controller.read_did(0xF190)
                    if not self.running:
                        break
                    step += 1
                    self.progress_signal.emit(int(step / self.total_steps * 100))
                else:
                    break

                # Step 5: 安全访问
                if self.running:
                    self.log_signal.emit("【自动化测试】请求安全访问种子...")
                    seed = self.controller.request_seed(0x01)
                    if not self.running or not seed:
                        break

                    dummy_key = [0xA5, 0xA5, 0xA5, 0xA5]
                    self.log_signal.emit("【自动化测试】发送密钥...")
                    result = self.controller.send_key(0x02, dummy_key)
                    if not self.running or not result:
                        break

                    self.log_signal.emit("【自动化测试】进入编程会话...")
                    self.controller.enter_programming_mode(
                        progress_callback=lambda p: self.progress_signal.emit(80 + int(p * 0.2))  # 从80%渐进到100%
                    )
                    if not self.running:
                        break
                    step += 1
                    self.progress_signal.emit(100)  # 强制设为100%

                else:
                    break

                self.log_signal.emit(f"【自动化测试】第 {self.current_round} 轮测试完成。")

        except Exception as e:
            self.log_signal.emit(f"【自动化测试】发生异常: {str(e)}")
        finally:
            self.progress_signal.emit(100)  # 强制设为100%
            self.controller.stop_all_requests()
            self.log_signal.emit("【自动化测试】测试流程已结束。")
            self.finished_signal.emit()
