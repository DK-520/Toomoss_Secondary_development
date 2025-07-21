from UDS_service import *
from time import sleep
import hashlib
from can import Message
import can
import socket
import struct
import UDS_OTA_Handler
import usb2can

# Windows平台缺少CMSG_SPACE的定义，添加模拟实现
if not hasattr(socket, 'CMSG_SPACE'):
    def CMSG_SPACE(length):
        return (length) + struct.calcsize("Iii")
    socket.CMSG_SPACE = CMSG_SPACE

# 添加CAN套接字配置兼容处理
if os.name == 'nt':  # Windows系统
    CAN_RAW = 1
    SOL_CAN_BASE = 0x65
    SOL_CAN_RAW = SOL_CAN_BASE + CAN_RAW
else:
    SOL_CAN_RAW = socket.SOL_CAN_RAW

from Crypto.Cipher import AES

# 新增：引入安全算法相关的常量和函数
SECURITY_COEFFICIENTS = bytes([0x22, 0x4D, 0x08, 0x31])  # Coef1-4

def calculate_key_from_seed(seed, level):
    """根据新安全算法计算Key"""
    hash_obj = hashlib.sha256(SECURITY_COEFFICIENTS)
    hash_digest = hash_obj.digest()

    KEY_L = hash_digest[:16]  # 低16字节作为KEY_L
    IV_L = hash_digest[16:]   # 高16字节作为IV_L

    cipher = AES.new(KEY_L, AES.MODE_CFB, IV_L[:16], segment_size=128)
    ciphertext = cipher.encrypt(seed)

    return ciphertext[:4]

class UDS_OTA:
    def __init__(self, device_handle, can_channel, console=None):
        self.device = device_handle
        self.channel = can_channel
        self.console = console
        self.progress = 0

    def _log(self, message):
        """日志记录函数，兼容console对象或print输出"""
        if hasattr(self.console, "log"):
            self.console.log(message)
        elif callable(self.console):
            self.console(message)
        else:
            print(message)

    def initialize_can(self):
        """
        使用 usb2can 初始化 CAN 控制器
        """
        # 创建 CAN 初始化配置
        can_config = CAN_INIT_CONFIG()
    
        # 设置波特率为 500Kbps (MCP_16MHz_500kBPS_CFG)
        can_config.CAN_BRP_CFG3 = MCP_16MHz_500kBPS_CFG3
        can_config.CAN_SJW = 1
        can_config.CAN_BS1_CFG1 = 12
        can_config.CAN_BS2_CFG2 = 5
        can_config.CAN_Mode = 0  # 正常模式
        can_config.CAN_ABOM = 1  # 自动离线管理
        can_config.CAN_NART = 1  # 禁止报文重传
        can_config.CAN_RFLM = 0  # FIFO锁定管理：新报文覆盖旧报文
        can_config.CAN_TXFP = 1  # 发送优先级管理：发送请求顺序决定
    
        # 调用 CAN 初始化函数
        ret = CAN_Init(self.device_handle, self.can_channel, byref(can_config))
        if ret != CAN_SUCCESS:
            return False
        return True
    def update_progress(self, value):
        self.progress = value
        if self.console:
            self.console.debug(f"OTA进度: {value}%")

    def enter_extended_session(self, addressing_type='physical'):
        """进入扩展会话，支持物理/功能寻址"""
        if self.console: self.console.debug(f"进入扩展会话({addressing_type})...")
        session_type = 0x03 if addressing_type == 'physical' else 0x83
        ret = send_diagnostic_session_control(self.device, self.channel, session_type, addressing_type, self.console)
        # 检查确认响应
        if ret and self._check_response(0x50):
            return ret
        return False

    def _check_response(self, expected_response):
        import time
        start_time = time.time()
        timeout = 2.0
        while time.time() - start_time < timeout:
            CanMsgBuffer = (CAN_MSG * 1024)()
            CanNum = CAN_GetMsg(self.device, self.channel, byref(CanMsgBuffer))
            if CanNum > 0:
                for i in range(CanNum):
                    response = CanMsgBuffer[i]
                    data = [response.Data[j] for j in range(response.DataLen)]
                    if len(data) >= 2 and data[1] == expected_response:
                        return True
            time.sleep(0.1)
        return False
    def wakeup(self):        # 发送唤醒信号
        if self.console: self.console.debug("发送唤醒信号...")
        msg = CAN_MSG()
        msg.ID = 0x33C
        msg.DataLen = 1
        msg.Data[0] = 0x02
        for i in range(1, 8):
            msg.Data[i] = 0x00
        ret = CAN_SendMsg(self.device, self.channel, byref(msg), 1)
        if ret != CAN_SUCCESS:
            self._log("发送唤醒信号失败")
            return False
        return True
    
    def perform_update(self, firmware_data):

        try:
            self._log("Starting OTA update process...")

        # 初始化 CAN 控制器
            if not self.initialize_can():
                return False

            self.wakeup()
            time.sleep(0.5)
            self.wakeup()

            # 进入扩展会话 (0x10 0x03)
            if not self.enter_extended_session('physical'):
                self._log("进入扩展会话 (0x10 0x03) 失败")
                return False
            self.update_progress(3)

            # 进入扩展会话 (0x10 0x83)
            if not self.enter_extended_session('functional'):
                self._log("进入扩展会话 (0x10 0x83) 失败")
                return False
            self.update_progress(9)

            # 关闭DTC设置 (0x85 0x82)
            if not self.control_dtc_setting(0x82):
                self._log("关闭DTC设置失败")
                return False
            self.update_progress(12)

            # 关闭通信 (0x28 0x83 0x03)
            if not self.control_communication(0x83, 0x03):
                self._log("关闭通信失败")
                return False
            self.update_progress(15)

            # 进入编程会话 (0x10 0x02)
            if not self.enter_programming_session():
                self._log("进入编程会话失败")
                return False
            self.update_progress(18)

            # 等待MCU重启(500ms)
            self._log("等待MCU重启(500ms)...")
            sleep(0.5)
            self.update_progress(21)

            # 解锁安全访问 (0x27)
            if not self.unlock_security():
                self._log("安全访问解锁失败")
                return False
            self.update_progress(24)

            # 写入指纹数据 (0x2E)
            if not self.write_fingerprint_data():
                self._log("写入指纹数据失败")
                return False
            self.update_progress(27)

            # 擦除APP内存 (0x31)
            if not self.erase_memory():
                self._log("内存擦除失败")
                return False
            self.update_progress(30)

            # 请求下载 (0x34)
            if not request_download(self.device, self.channel, 0x08000000, len(firmware_data)):
                self._log("请求下载失败")
                return False
            # 这里假设最大块大小确认后更新进度，具体根据实际情况调整
            self.update_progress(30 + (80 - 30) * 0.1)

            # 传输数据 (0x36)
            if not self.transfer_data(firmware_data):
                self._log("数据传输失败")
                return False

            # 检查内存完整性 (0x31)
            if not self.check_memory_integrity():
                self._log("内存完整性检查失败")
                return False
            self.update_progress(83)

            # 检查程序兼容性 (0x31)
            # 这里假设存在检查程序兼容性的函数
            if not self._check_program_compatibility():
                self._log("程序兼容性检查失败")
                return False
            self.update_progress(86)

            # ECU硬复位 (0x11)
            if not self.ecu_reset(0x01):
                self._log("ECU硬复位失败")
                return False
            self.update_progress(89)

            # 等待MCU重启(2000ms)
            self._log("等待MCU重启(2000ms)...")
            sleep(2)
            self.update_progress(92)

            # 进入默认会话 (0x10 0x81)
            if not self.enter_default_session():
                self._log("进入默认会话失败")
                return False
            self.update_progress(95)

            # 清除所有DTC (0x14 0xFF 0xFF 0xFF)
            if not self._clear_all_dtc():
                self._log("清除所有DTC失败")
                return False
            self.update_progress(100)

            self._log("OTA更新成功完成")
            return True
        except Exception as e:
            self._log(f"OTA更新失败: {str(e)}")
            self._log(f"当前进度: {self.progress}%")
            return False

    def _check_program_compatibility(self):
        # 这里需要实现检查程序兼容性的逻辑
        if self.console: self.console.debug("检查程序兼容性...")
        msg = CAN_MSG()
        msg.ID = 0x713 if addressing_type == 'physical' else 0x7DF
        msg.DataLen = 8
        msg.Data[0] = 0x04
        msg.Data[1] = 0x31
        # 填充其他数据
        for i in range(2, 8):
            msg.Data[i] = 0x00
        ret = CAN_SendMsg(self.device, self.channel, byref(msg), 1)
        if ret != 0:
            if self.console: self.console.error("发送程序兼容性检查请求失败")
            return False
        return self._check_response(0x71)

    def _clear_all_dtc(self):
        if self.console: self.console.debug("清除所有DTC...")
        msg = CAN_MSG()
        msg.ID = 0x7DF
        msg.DataLen = 8
        msg.Data[0] = 0x04
        msg.Data[1] = 0x14
        msg.Data[2] = 0xFF
        msg.Data[3] = 0xFF
        msg.Data[4] = 0xFF
        for i in range(5, 8):
            msg.Data[i] = 0x00
        ret = CAN_SendMsg(self.device, self.channel, byref(msg), 1)
        if ret != 0:
            if self.console: self.console.error("发送清除所有DTC请求失败")
            return False
        return self._check_response(0x54)

    def enter_programming_session(self):
        """进入编程会话"""
        if self.console: self.console.debug("进入编程会话...")
        ret = send_diagnostic_session_control(self.device, self.channel, 0x02, self.console)
        self.update_progress(7)  # 更新进度
        return ret
        
    def check_programming_condition(self, console=None):
        """检查编程条件"""
        if self.console: self.console.debug("检查编程条件...")
        msg = CAN_MSG()
        msg.ID = 0x7DF
        msg.DataLen = 8
        msg.Data[0] = 0x04
        msg.Data[1] = 0x31
        msg.Data[2] = 0x01
        msg.Data[3] = 0x02
        for i in range(4, 8):
            msg.Data[i] = 0x00
            
        # 发送请求
        ret = CAN_SendMsg(self.device, self.channel, byref(msg), 1)
        if ret != 0:
            if self.console: self.console.error("发送编程条件检查请求失败")
            return False
        
        # 添加响应接收逻辑
        import time
        start_time = time.time()
        timeout = 2.0
        while time.time() - start_time < timeout:
            CanMsgBuffer = (CAN_MSG * 1024)()
            CanNum = CAN_GetMsg(self.device, self.channel, byref(CanMsgBuffer))
            if CanNum > 0:
                for i in range(CanNum):
                    response = CanMsgBuffer[i]
                    if response.ID == 0x71b:  # 过滤目标ECU响应
                        data = [response.Data[j] for j in range(response.DataLen)]
                        if self.console: 
                            console.debug(f"收到编程条件检查响应: {[hex(x) for x in data]}")
                        # 检查正响应 (71 + 31 + 01)
                        if len(data) >= 3 and data[1] == 0x71 and data[2] == 0x31 and data[3] == 0x01:
                            self.update_progress(10)
                            return True
                        # 检查负响应 (7F + 31 + NRC)
                        elif len(data) >= 4 and data[1] == 0x7F and data[2] == 0x31:
                            nrc = data[3]
                            if self.console: 
                                console.error(f"编程条件检查失败，NRC: {hex(nrc)}")
                            return False
            time.sleep(0.1)
        
        if self.console: self.console.error("编程条件检查超时")
        return False
    
    def unlock_security(self, level=0x01):
        """解锁安全访问"""
        if self.console: self.console.debug("解锁安全访问...")
        seed = request_security_access(self.device, self.channel, level, self.console)
        if not seed:
            return False
            
        key = calculate_key_from_seed(seed, level)  # 使用新的安全算法计算密钥
        ret = send_security_key(self.device, self.channel, level, key)
        self.update_progress(35)
        return ret
    
    def write_fingerprint_data(self):
        """写入指纹数据"""
        if self.console: self.console.debug("写入指纹数据...")
        msg = CAN_MSG()
        msg.ID = 0x7DF
        msg.DataLen = 12
        msg.Data[0] = 0x0C
        msg.Data[1] = 0x2E
        msg.Data[2] = 0xF1
        msg.Data[3] = 0x84
        msg.Data[4] = 0x41  # 示例数据
        msg.Data[5] = 0x42
        msg.Data[6] = 0x43
        msg.Data[7] = 0x44
        msg.Data[8] = 0x45
        msg.Data[9] = 0x46
        msg.Data[10] = 0x20
        for i in range(11, 12):
            msg.Data[i] = 0x00
            
        ret = CAN_SendMsg(self.device, self.channel, byref(msg), 1)
        self.update_progress(40)
        return ret == 0
    
    def erase_memory(self):
        """擦除内存"""
        if self.console: self.console.debug("擦除内存...")
        msg = CAN_MSG()
        msg.ID = 0x7DF
        msg.DataLen = 8
        msg.Data[0] = 0x04
        msg.Data[1] = 0x31
        msg.Data[2] = 0x01
        msg.Data[3] = 0xFF
        for i in range(4, 8):
            msg.Data[i] = 0x00
            
        ret = CAN_SendMsg(self.device, self.channel, byref(msg), 1)
        self.update_progress(45)
        return ret == 0
    
    def transfer_data(self, firmware_data):
        """传输数据"""
        if self.console: self.console.debug("传输数据...")
        
        # 1. 请求下载(0x34)
        if not request_download(self.device, self.channel, 0x08000000, len(firmware_data)):
            return False
            
        # 2. 传输数据(0x36)
        block_size = 1024  # 每次传输1KB
        for i in range(0, len(firmware_data), block_size):
            block = firmware_data[i:i+block_size]
            if not transfer_data(self.device, self.channel, i//block_size + 1, block):
                return False
                
        # 3. 请求退出传输(0x37)
        ret = request_transfer_exit(self.device, self.channel)
        self.update_progress(70)
        return ret
    
    def control_dtc_setting(self, sub_function, addressing_type='functional'):
        return control_dtc_setting(self.device, self.channel, sub_function, addressing_type, self.console)

    def control_communication(self, channel, control_type, addressing_type='functional'):
        return control_communication(self.device, self.channel, channel, control_type, addressing_type, self.console)

    def check_memory_integrity(self):
        return check_memory_integrity(self.device, self.channel, self.console)

    def ecu_reset(self, reset_type=0x01):
        return ecu_reset(self.device, self.channel, reset_type, self.console)

    def enter_default_session(self, addressing_type='functional'):
        return enter_default_session(self.device, self.channel, addressing_type, self.console)


def convert_to_ctypes(message):
    # 这里需要根据实际的 Message 类和 ctypes 类型进行转换
    # 以下是示例代码，需要根据具体情况修改
    from ctypes import Structure, c_uint32, c_uint8
    class CANMessage(Structure):
        _fields_ = [
            ('arbitration_id', c_uint32),
            ('is_extended_id', c_uint8),
            ('data', c_uint8 * 8)
        ]
    c_msg = CANMessage()
    c_msg.arbitration_id = message.arbitration_id
    c_msg.is_extended_id = message.is_extended_id
    for i in range(8):
        c_msg.data[i] = message.data[i]
    return c_msg