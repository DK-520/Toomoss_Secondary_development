from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread
from datetime import datetime
import os

class UDSConsole(QObject):
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    
    log_signal = pyqtSignal(str, int)  # message, level
    
    def __init__(self, log_file=None):
        super().__init__()
        self.log_file = log_file
        if log_file:
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)
    
    def _log(self, level, message):
        """内部日志方法"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level_str = {
            self.DEBUG: "DEBUG",
            self.INFO: "INFO",
            self.WARNING: "WARNING",
            self.ERROR: "ERROR"
        }.get(level, "INFO")
        
        formatted_msg = f"[{timestamp}] [{level_str}] {message}"
        
        # 发送信号到UI
        self.log_signal.emit(formatted_msg, level)
        
        # 写入日志文件
        if self.log_file:
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(formatted_msg + "\n")
            except Exception as e:
                self.log_signal.emit(f"日志文件写入失败: {str(e)}", self.ERROR)
    
    def debug(self, message):
        self._log(self.DEBUG, message)
    
    def info(self, message):
        self._log(self.INFO, message)
    
    def warning(self, message):
        self._log(self.WARNING, message)
    
    def error(self, message):
        self._log(self.ERROR, message)
    
    # 保持向后兼容
    def log(self, message):
        self.info(message)
