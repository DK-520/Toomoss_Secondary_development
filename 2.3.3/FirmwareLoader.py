import os
from PyQt5.QtWidgets import QFileDialog

class FirmwareLoader:
    def __init__(self, console):
        self.console = console

    def load_hex_file(self, file_path):
        """加载 .hex 文件并返回固件数据(跳过解析直接读取二进制)"""
        try:
            self.console.log_message("警告：跳过hex文件解析，直接读取二进制内容", "WARNING")
            with open(file_path, 'rb') as file:
                return file.read()
        except FileNotFoundError:
            self.console.log_message("文件未找到，请检查路径是否正确", "ERROR")
            return None