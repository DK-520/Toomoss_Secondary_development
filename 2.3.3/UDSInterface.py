# -*- coding: utf-8 -*-
import sys
from functools import partial
import self
import UDS_service
import os  # 新增：导入 os 模块
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QDialog,
    QHBoxLayout, QPushButton, QLabel, QTextEdit, QComboBox,
    QFileDialog, QProgressBar, QMessageBox, QLineEdit, QSystemTrayIcon, QMenu, QAction
)
from PyQt5.QtGui import QRegExpValidator, QIcon
from PyQt5.QtCore import QRegExp, Qt, pyqtSlot
from UDSController import UDSController
import UDS_OTA_Handler
from UDSTestRunner import *
from UDSConsole import UDSConsole
from UDS_OTA_Module import OTAWorker
from time import sleep
from ctypes import byref
from CAN_Receive import CANReceiver
from usb2can import CAN_MSG
import UDS_OTA


class CloseDialog(QDialog):
    """自定义关闭确认对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('关闭选项')
        """self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint)  # 隐藏关闭按钮"""
        # 移除问号帮助按钮
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout()
        self.setLayout(layout)

        # 提示文本
        label = QLabel("确定要关闭窗口吗？")
        layout.addWidget(label, alignment=Qt.AlignCenter)

        # 按钮布局
        btn_layout = QHBoxLayout()

        # 最小化按钮
        self.minimize_btn = QPushButton("最小化")
        self.minimize_btn.setFixedWidth(100)
        btn_layout.addWidget(self.minimize_btn)

        # 退出按钮
        self.exit_btn = QPushButton("退出")
        self.exit_btn.setFixedWidth(100)
        btn_layout.addWidget(self.exit_btn)

        layout.addLayout(btn_layout)

        # 设置按钮信号
        self.minimize_btn.clicked.connect(lambda: self.done(1))
        self.exit_btn.clicked.connect(lambda: self.done(2))


class UDSInterface(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UDS Tester")
        self.setGeometry(100, 100, 800, 700)

        # 初始化组件
        self.console = UDSConsole()
        self.controller = UDSController(self.console)
        self.can_receiver = None

        # 连接信号
        self.console.log_signal.connect(self.update_log)

        # 系统托盘初始化
        self.init_tray_icon()
        self.tray_icon.show()
        self.tray_icon = QSystemTrayIcon(self)

        # 主界面布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 设备状态与连接按钮
        self.connect_button = QPushButton("连接设备")
        self.status_label = QLabel("设备状态: 未连接")
        main_layout.addWidget(self.connect_button)
        main_layout.addWidget(self.status_label)

        # 功能区域
        self._setup_functional_buttons(main_layout)

        # 自定义 CAN 报文发送区域
        self._setup_custom_can_section(main_layout)

        # 接收消息显示区域
        self.recv_text = QTextEdit()
        self.recv_text.setReadOnly(True)
        self.recv_text.setFixedHeight(150)
        main_layout.addWidget(QLabel("接收到的消息:"))
        main_layout.addWidget(self.recv_text)

        # 日志区域
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(150)
        main_layout.addWidget(QLabel("操作日志:"))
        main_layout.addWidget(self.log_text)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # 自动化测试输入框和按钮
        test_control_layout = QHBoxLayout()
        self.repeat_input = QLineEdit("1")
        self.repeat_input.setFixedWidth(50)
        self.stop_test_btn = QPushButton("停止测试")
        self.auto_test_btn = QPushButton("启动自动化测试")  # ✅ 新增按钮定义
        test_control_layout.addWidget(QLabel("测试次数:"))
        test_control_layout.addWidget(self.repeat_input)
        test_control_layout.addWidget(self.stop_test_btn)
        test_control_layout.addWidget(self.auto_test_btn)
        test_control_layout.addStretch()
        main_layout.addLayout(test_control_layout)

        # 自动化测试线程
        self.auto_test_runner = None

        # 绑定事件
        self.connect_button.clicked.connect(self.toggle_connection)
        self.send_custom_btn.clicked.connect(self.send_custom_can_message)
        self.auto_test_btn.clicked.connect(self.start_automation_test)  # ✅ 绑定点击事件

        # 初始化 UI 状态
        self.set_ui_to_disconnected_state()

    def update_progress_bar(self, percent):
        self.progress_bar.setValue(int(percent))

    def init_tray_icon(self):
        """初始化系统托盘图标"""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("icon.ico"))  # 替换为你自己的图标路径

        tray_menu = QMenu()
        minimize_action = QAction("最小化", self)
        restore_action = QAction("还原", self)
        quit_action = QAction("退出", self)

        tray_menu.addAction(minimize_action)
        tray_menu.addAction(restore_action)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)

        minimize_action.triggered.connect(self.hide)
        restore_action.triggered.connect(self.showNormal)
        quit_action.triggered.connect(QApplication.instance().quit)

        self.tray_icon.show()

    def _setup_functional_buttons(self, layout):
        """初始化功能按钮"""
        # 会话控制组
        self.session_group = QWidget()
        session_layout = QHBoxLayout()
        self.default_session_btn = QPushButton("默认会话")
        self.extended_session_btn = QPushButton("扩展会话")
        self.default_session_btn.clicked.connect(partial(self.set_session, 0x01))
        self.extended_session_btn.clicked.connect(partial(self.set_session, 0x03))
        session_layout.addWidget(self.default_session_btn)
        session_layout.addWidget(self.extended_session_btn)
        self.session_group.setLayout(session_layout)
        layout.addWidget(self.session_group)

        # 安全访问组
        self.security_group = QWidget()
        security_layout = QHBoxLayout()
        self.seed_btn = QPushButton("请求种子")
        self.key_btn = QPushButton("发送密钥")
        self.seed_btn.clicked.connect(self.request_seed)
        self.key_btn.clicked.connect(self.send_key)
        security_layout.addWidget(self.seed_btn)
        security_layout.addWidget(self.key_btn)
        self.security_group.setLayout(security_layout)
        layout.addWidget(self.security_group)

        # DID读取组
        self.read_did_group = QWidget()
        read_did_layout = QHBoxLayout()
        self.version_btn = QPushButton("读取版本号")
        self.did_combo = QComboBox()
        self.read_did_btn = QPushButton("读取DID")
        self.did_combo.addItems(["F190", "F18C", "F187"])
        self.version_btn.clicked.connect(self.read_version)
        read_did_layout.addWidget(self.version_btn)
        read_did_layout.addWidget(self.did_combo)
        read_did_layout.addWidget(self.read_did_btn)
        self.read_did_group.setLayout(read_did_layout)
        layout.addWidget(self.read_did_group)

        # 编程模式 & 固件更新
        self.programming_mode_btn = QPushButton("进入编程模式")
        self.programming_mode_btn.clicked.connect(self.enter_programming_mode)
        layout.addWidget(self.programming_mode_btn)

        self.firmware_btn = QPushButton("执行固件更新")
        self.firmware_btn.clicked.connect(self.firmware_update)
        layout.addWidget(self.firmware_btn)

        # 新增 OTA 更新按钮
        self.ota_update_btn = QPushButton("启动OTA更新")
        self.ota_update_btn.clicked.connect(self.start_ota_update)
        layout.addWidget(self.ota_update_btn)

    def _setup_custom_can_section(self, layout):
        """设置自定义 CAN 报文发送区域"""
        self.custom_can_group = QWidget()
        self.custom_can_layout = QVBoxLayout()

        id_dlc_layout = QHBoxLayout()
        self.can_id_input = QLineEdit("7DF")
        self.can_dlc_input = QLineEdit("8")
        self.can_id_input.setFixedWidth(80)
        self.can_dlc_input.setFixedWidth(40)
        id_dlc_layout.addWidget(QLabel("ID (Hex):"))
        id_dlc_layout.addWidget(self.can_id_input)
        id_dlc_layout.addWidget(QLabel("DLC:"))
        id_dlc_layout.addWidget(self.can_dlc_input)
        id_dlc_layout.addStretch()

        data_input_layout = QHBoxLayout()
        self.can_data_inputs = []
        for i in range(8):
            byte_layout = QVBoxLayout()
            label = QLabel(f"Byte{i}")
            line_edit = QLineEdit("00")
            line_edit.setFixedWidth(50)
            line_edit.setValidator(QRegExpValidator(QRegExp("[0-9A-Fa-f]{0,2}")))
            byte_layout.addWidget(label, alignment=Qt.AlignCenter)
            byte_layout.addWidget(line_edit)
            data_input_layout.addLayout(byte_layout)
            self.can_data_inputs.append(line_edit)

        self.send_custom_btn = QPushButton("发送自定义CAN报文")
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.send_custom_btn)
        button_layout.addStretch()

        self.custom_can_layout.addLayout(id_dlc_layout)
        self.custom_can_layout.addLayout(data_input_layout)
        self.custom_can_layout.addLayout(button_layout)
        self.custom_can_group.setLayout(self.custom_can_layout)
        layout.addWidget(self.custom_can_group)

    def start_automation_test(self):
        if not self.controller.connected:
            QMessageBox.warning(self, "警告", "请先连接设备再启动自动化测试！")
            return
        try:
            repeat_times = int(self.repeat_input.text())
        except ValueError:
            QMessageBox.warning(self, "警告", "请输入有效的测试次数！")
            return

        self.progress_bar.setValue(0)
        self.console.log(f"启动自动化测试，共 {repeat_times} 次")

        if self.auto_test_runner is not None:
            self.auto_test_runner.stop()
            self.auto_test_runner.wait()

        self.auto_test_runner = UDSTestRunner(self.controller)
        self.auto_test_runner.set_repeat(repeat_times)
        self.auto_test_runner.log_signal.connect(self.update_log)
        self.auto_test_runner.progress_signal.connect(self.update_progress_bar)
        self.auto_test_runner.finished_signal.connect(self.on_test_finished)

        self.auto_test_runner.start()
        self.stop_test_btn.setEnabled(True)
        self.auto_test_btn.setEnabled(False)

    def on_test_finished(self):
        self.stop_test_btn.setEnabled(False)
        self.auto_test_btn.setEnabled(True)
        if self.auto_test_runner is not None:
            self.auto_test_runner = None

    def toggle_connection(self):
        if self.connect_button.text() == "连接设备":
            self.connect_device()
        else:
            reply = QMessageBox.question(
                self, '确认', '确定要断开设备吗？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.disconnect_device()

    def connect_device(self):
        self.console.log("正在连接设备...")
        ret, handles = self.controller.usb_handler.scan_devices()
        if ret > 0:
            if self.controller.connect_device():
                self.console.log("设备连接成功！")
                self.status_label.setText("设备状态: 已连接")
                self.connect_button.setText("断开设备")
                self.enable_operational_buttons()
                self.start_can_receiver()
            else:
                self.console.log("设备连接失败")
        else:
            self.console.error("未检测到设备")
            QMessageBox.critical(self, "错误", "未找到可用设备！")

    def disconnect_device(self):
        self.console.log("正在断开设备...")

        self.set_ui_to_disconnected_state()
        self.connect_button.setText("连接设备")
        self.connect_button.setEnabled(True)

        if hasattr(self, 'can_receiver'):
            try:
                self.can_receiver.stop()
                self.can_receiver.wait()
                del self.can_receiver
            except Exception as e:
                self.console.error(f"关闭 CAN 接收器失败：{str(e)}")  # 这一行需要正确缩进

        if self.controller.disconnect_device():
            self.console.log("设备已成功断开")
        else:
            self.console.log("设备断开失败")

    def start_can_receiver(self):
        if not self.controller.connected:
            return
        device_handle = self.controller.usb_handler.DevHandles[0]
        can_channel = self.controller.can_controller.CANChannel
        self.can_receiver = CANReceiver(device_handle, can_channel, CAN_MSG)
        self.can_receiver.message_received.connect(self.handle_received_message)
        self.can_receiver.start()

    def handle_received_message(self, msg):
        data = [msg.Data[i] for i in range(msg.DataLen)]
        formatted_data = ' '.join([f"{b:02X}" for b in data])
        self.console.debug(f"【接收】ID={hex(msg.ID)}, DLC={msg.DataLen}, 数据=[{formatted_data}]")
        self.recv_text.append(f"ID: {hex(msg.ID)} | DLC: {msg.DataLen} | 数据: {formatted_data}")
        self.recv_text.verticalScrollBar().setValue(self.recv_text.verticalScrollBar().maximum())

    def set_ui_to_disconnected_state(self):
        buttons = [
            self.default_session_btn, self.extended_session_btn,
            self.seed_btn, self.key_btn,
            self.version_btn, self.read_did_btn, self.firmware_btn,
            self.programming_mode_btn, self.auto_test_btn
        ]
        for btn in buttons:
            btn.setEnabled(False)
        self.connect_button.setEnabled(True)
        self.status_label.setText("设备状态: 未连接")
        self.log_text.clear()
        self.progress_bar.setValue(0)

    def enable_operational_buttons(self):
        buttons = [
            self.default_session_btn, self.extended_session_btn,
            self.seed_btn, self.version_btn,
            self.programming_mode_btn, self.auto_test_btn
        ]
        for btn in buttons:
            btn.setEnabled(True)

    def send_custom_can_message(self):
        if not self.controller.connected:
            self.console.error("错误：设备未连接，请先连接。")
            return

        device_handle = self.controller.usb_handler.DevHandles[0]
        can_channel = self.controller.can_controller.CANChannel

        try:
            can_id = int(self.can_id_input.text(), 16)
            dlc = int(self.can_dlc_input.text())
            data_bytes = [int(le.text() or "00", 16) for le in self.can_data_inputs]

            from usb2can import CAN_MSG, CAN_SendMsg, CAN_GetMsg

            msg = CAN_MSG()
            msg.ID = can_id
            msg.DataLen = dlc
            for i in range(dlc):
                msg.Data[i] = data_bytes[i]

            ret = CAN_SendMsg(device_handle, can_channel, byref(msg), 1)
            if ret >= 0:
                self.console.log(f"成功发送报文 ID={hex(can_id)}, DLC={dlc}, Data={[hex(b) for b in data_bytes[:dlc]]}")
            else:
                self.console.error(f"发送失败，错误码: {ret}")

            CanMsgBuffer = (type(msg) * 1024)()
            CanNum = CAN_GetMsg(device_handle, can_channel, byref(CanMsgBuffer))
            if CanNum > 0:
                for i in range(CanNum):
                    data = [CanMsgBuffer[i].Data[j] for j in range(CanMsgBuffer[i].DataLen)]
                    self.console.log(f"收到响应 ID={hex(CanMsgBuffer[i].ID)}, 数据={[hex(x) for x in data]}")
            elif CanNum == 0:
                self.console.log("未收到响应")
            else:
                self.console.log("接收报文失败")

        except Exception as e:
            self.console.error(f"输入错误: {str(e)}")

    def update_log(self, message):
        self.log_text.append(message)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def set_session(self, session_type):
        self.console.log(f"设置会话类型: {session_type:02X}")
        self.controller.set_session(session_type)
        self.console.log(f"已切换到会话类型: {session_type:02X}")

    def request_seed(self):
        self.console.log("请求安全访问种子...")
        if self.controller.request_seed(0x11):
            self.console.log("种子请求已发送，等待响应...")

    def send_key(self):
        self.console.log("发送安全访问密钥...")
        dummy_key = [0xA5, 0xA5, 0xA5, 0xA5]
        if self.controller.send_key(0x02, dummy_key):
            self.console.log("密钥已发送")

    def read_version(self):
        if not self.controller.connected:
            self.console.error("错误：设备未连接，无法读取版本号")
            return
        self.controller.read_version()

    def read_did(self):
        did = int(self.did_combo.currentText(), 16)
        self.console.log(f"读取DID: {did:04X}")
        self.controller.read_did(did)

    def firmware_update(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择固件文件")
        if file_path:
            try:
                with open(file_path, 'rb') as f:
                    firmware_data = list(f.read())
                self.console.log("开始固件更新流程...")

                def update_progress(percent):
                    self.progress_bar.setValue(percent)
                    if percent == 100:
                        self.console.log("固件更新完成")

                if self.controller.firmware_update(firmware_data, update_progress):
                    self.console.log("固件更新成功")
                else:
                    self.console.log("固件更新失败")
            except Exception as e:
                self.console.error(f"固件更新异常: {str(e)}")
                QMessageBox.critical(self, "错误", f"读取或更新固件时发生错误:\n{str(e)}")

    def enter_programming_mode(self):
        """直接进入编程会话"""
        if not self.controller.connected:
            self.console.error("设备未连接")
            return False
        
        device_handle = self.controller.usb_handler.DevHandles[0]
        can_channel = self.controller.can_controller.CANChannel
        
        self.console.log("尝试进入编程会话...")
        try:
            from usb2can import CAN_GetMsg  # 确保导入CAN_GetMsg
            result = UDS_service.send_diagnostic_session_control(
                device_handle, can_channel, 0x02, self.console
            )
            
            # 获取最后接收到的消息
            CanMsgBuffer = (CAN_MSG * 1024)()
            CanNum = CAN_GetMsg(device_handle, can_channel, byref(CanMsgBuffer))
            
            # 记录所有接收到的消息
            if CanNum > 0:
                for i in range(CanNum):
                    data = [CanMsgBuffer[i].Data[j] for j in range(CanMsgBuffer[i].DataLen)]
                    self.console.debug(f"接收到的响应 {i+1}/{CanNum}: ID={hex(CanMsgBuffer[i].ID)}, 数据={[hex(x) for x in data]}")

            if CanNum > 0:
                for i in range(CanNum):
                    data = [CanMsgBuffer[i].Data[j] for j in range(CanMsgBuffer[i].DataLen)]
                    
                    # 解析响应数据
                    if len(data) >= 3 and data[1] == 0x50:  # 正响应
                        if data[2] == 0x02:  # 检查会话类型是否为编程模式
                            self.console.log("成功进入编程模式")
                            return True
                        else:
                            self.console.error(f"进入编程会话失败 - 不正确的会话类型: {hex(data[2])}")
                            return False
                    elif len(data) >= 4 and data[1] == 0x7F:  # 负响应
                        nrc = data[3]
                        self.console.error(f"进入编程会话失败 - NRC 错误码: {hex(nrc)}")
                        return False
                    else:
                        self.console.warning(f"收到未知响应: {[hex(x) for x in data]}")
            
            # 如果没有明确的错误响应，则认为成功
                if result:
                    self.console.log("成功进入编程模式")
                    return True
                else:
                    self.console.error("进入编程会话失败 - 服务返回失败")
                    return False
            
        except Exception as e:
            self.console.error(f"进入编程会话时发生异常: {str(e)}")
            return False

    def stop_automation_test(self):
        if hasattr(self, 'auto_test_runner') and self.auto_test_runner.isRunning():
            self.auto_test_runner.stop()
            self.auto_test_runner.wait()
            self.auto_test_runner = None
        self.stop_test_btn.setEnabled(False)
        self.auto_test_btn.setEnabled(True)

    def closeEvent(self, event):
        """重写 closeEvent，使用自定义对话框"""
        dialog = CloseDialog(self)
        result = dialog.exec_()

        if result == 1:  # 最小化
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "UDS Tester",
                "程序已最小化到系统托盘",
                QSystemTrayIcon.Information,
                2000
            )
        elif result == 2:  # 退出
            self.disconnect_device()  # 断开设备连接
            self.stop_background_threads()  # 停止后台线程
            event.accept()
        else:  # 点击外部区域
            event.ignore()

    def stop_background_threads(self):
        """停止所有后台线程，防止退出时崩溃"""
        # 确保 can_receiver 已初始化
        if hasattr(self, 'can_receiver') and self.can_receiver and self.can_receiver.isRunning():
            self.can_receiver.stop()
            self.can_receiver.wait(2000)  # 等待最多2秒

        if hasattr(self, 'auto_test_runner') and self.auto_test_runner.isRunning():
            self.auto_test_runner.stop()
            self.auto_test_runner.wait(2000)

        # 如果有其他线程也在这里加入清理

    def _show_minimized_notification(self):
        """显示最小化通知"""
        self.tray_icon.showMessage(
            "UDS Tester",
            "程序已最小化到系统托盘",
            QSystemTrayIcon.Information,
            2000
        )

    def load_firmware_file(self, file_path):
        """
        加载固件文件（支持 .bin 和 .hex 格式）
        :param file_path: 文件路径
        :return: 固件数据 (bytes) 和文件大小 (int)
        """
        if not os.path.exists(file_path):
            self.console.error(f"错误：文件不存在 - {file_path}")
            return None, 0

        try:
            # 判断文件类型
            if file_path.endswith('.bin'):
                with open(file_path, 'rb') as f:
                    firmware_data = list(f.read())
                self.console.log(f"成功读取 .bin 文件，大小: {len(firmware_data)} 字节")
                return bytes(firmware_data), len(firmware_data)

            elif file_path.endswith('.hex'):
                # 跳过hex解析，直接读取二进制内容
                self.console.warning("跳过hex文件解析，直接读取二进制内容")
                with open(file_path, 'rb') as f:
                    firmware_data = f.read()
                self.console.log(f"成功读取 .hex 文件(作为二进制)，大小: {len(firmware_data)} 字节")
                return firmware_data, len(firmware_data)

            else:
                self.console.error("不支持的文件格式，请选择 .bin 或 .hex 文件")
                return None, 0

        except Exception as e:
            self.console.error(f"读取或解析固件文件时发生异常: {str(e)}")
            return None, 0


    def start_ota_update(self):
        """启动OTA更新流程"""
        if not self.controller.connected:
            QMessageBox.warning(self, "警告", "请先连接设备再启动OTA更新！")
            return

        file_path, _ = QFileDialog.getOpenFileName(self, "选择固件文件", "", "Binary Files (*.bin *.hex);;All Files (*)")
        if not file_path:
            self.console.log("固件更新已取消")
            return

        # 定义进度更新回调函数
        def update_progress(percent):
            self.progress_bar.setValue(percent)
            if percent == 100:
                self.console.log("固件传输完成")
            elif percent % 10 == 0:  # 每10%记录一次日志
                self.console.log(f"固件更新进度: {percent}%")

        try:
            self.console.log(f"开始读取固件文件: {file_path}")
            firmware_data, firmware_size = self.load_firmware_file(file_path)
            if firmware_data is None or firmware_size == 0:
                self.console.error("无法加载固件文件，OTA更新已取消")
                return

            self.console.log(f"成功读取固件文件，大小: {firmware_size}字节")

            self.console.log("开始OTA更新流程...")
            # 使用UDS_OTA_Handler进行升级

            device_handle = self.controller.usb_handler.DevHandles[0]
            can_channel = self.controller.can_controller.CANChannel
            self.uds_ota = UDS_OTA_Handler.UDS_OTA_Handler(device_handle, can_channel, console=self.console)
            self.uds_ota.progress_monitor.progress_signal.connect(self.update_progress_bar)
            self.uds_ota.progress_monitor.log_signal.connect(self.update_log)
            success = self.uds_ota.perform_ota_update(firmware_data=file_path)

            if success:
                self.console.log("OTA更新成功")
                QMessageBox.information(self, "成功", "OTA更新完成")
            else:
                self.console.log("OTA更新失败")
                QMessageBox.critical(self, "错误", "OTA更新失败")

        except Exception as e:
            self.console.error(f"OTA更新异常: {str(e)}")
            QMessageBox.critical(self, "错误", f"OTA更新时发生错误:\n{str(e)}")
