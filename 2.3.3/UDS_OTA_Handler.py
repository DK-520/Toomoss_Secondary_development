from ctypes import byref
import time
import binascii
import hashlib
from datetime import datetime
import sys
from pathlib import Path
import can
import isotp

from PyQt5.QtCore import QObject, pyqtSignal
from usb2can import CAN_INIT_CONFIG, CAN_Init, CAN_SUCCESS
import os
from Crypto.Cipher import AES
import UDS_service

# 新增：引入安全算法相关的常量和函数
SECURITY_COEFFICIENTS = bytes([0x22, 0x4D, 0x08, 0x31])   # Coef1-4

def calculate_key_from_seed(seed, level):
    """uds_tester.py中的标准安全算法实现"""
    hash_obj = hashlib.sha256(SECURITY_COEFFICIENTS)
    hash_digest = hash_obj.digest()

    KEY_L = hash_digest[:16]  # 低16字节作为KEY_L
    IV_L = hash_digest[16:]   # 高16字节作为IV_L

    cipher = AES.new(KEY_L, AES.MODE_CFB, IV_L[:16], segment_size=128)
    ciphertext = cipher.encrypt(seed)

    return ciphertext[:4]  # 返回前4字节作为Key


class DataTransferInfo:
    def __init__(self):
        self.app_FileBufferAscii = b'' # Your application file content
        self.app_size = 0
        self.app_36_len = 0 # Length for 36 service transfer
        self.app_section = 1 # Number of sections for download (assuming one for simplicity)
        self.app_start_addr = [[0x08000000, 0x00000400]] # Example start address for a section

data_transfer_info = DataTransferInfo()

class OTAProgressMonitor(QObject):
    progress_signal = pyqtSignal(float)
    log_signal = pyqtSignal(str)

class UDS_OTA_Handler:
    def __init__(self, device_handle, can_channel, console=None):
        self.device_handle = device_handle
        self.can_channel = can_channel
        self.console = console or print
        self.progress_monitor = OTAProgressMonitor()
        self.ota_update_progress = 0.0

        # 初始化CAN总线
        try:
            from ldxn import CANalystIIBus
            self.canbus = CANalystIIBus(self.device_handle, self.can_channel, 500000)
        except Exception as e:
            self._log(f"Failed to initialize CAN bus: {e}")
            raise

    def _log(self, message):
        """日志记录函数，兼容console对象或print输出"""
        # 判断console对象是否有log方法
        if hasattr(self.console, "log"):
            # 如果有log方法，则调用log方法输出日志
            self.console.log(message)
        else:
            # 如果没有log方法，则调用print方法输出日志
            print(message)

    def increase_progress(self):
        for _ in range(3):  # Mimics the CAPL loop
            self.ota_update_progress += 0.38
            self.progress_monitor.progress_signal.emit(self.ota_update_progress)

    def current_update_progress(self, progress_value):
        self._log(f"======> {int(progress_value)}%")
        self.progress_monitor.progress_signal.emit(int(progress_value))

    def testWaitForTimeout(self, ms):
        time.sleep(ms / 1000.0)  # 原逻辑保持毫秒转秒

    def send_uds_request(self, isotp_stack, data, addressing_type="physical", timeout=5):
        self._log(f"Sending UDS request ({addressing_type}): {binascii.hexlify(data).decode('utf-8').upper()}")
        try:
            isotp_stack.send(data)
            start_time = time.time()
            while time.time() - start_time < timeout:
                isotp_stack.process()
                response = isotp_stack.recv()
                if response is not None:
                    self._log(f"Received UDS response ({addressing_type}): {binascii.hexlify(response).decode('utf-8').upper()}")
                    return response
                time.sleep(0.001)
            self._log("UDS response timeout.")
            return None
        except Exception as e:
            self._log(f"Error sending/receiving UDS: {e}")
            return None

    def send_uds_request_functional(self, isotp_func_stack, data, timeout=5):
        self._log(f"Sending UDS functional request: {binascii.hexlify(data).decode('utf-8').upper()}")
        try:
            isotp_func_stack.send(data)
            start_time = time.time()
            while time.time() - start_time < timeout:
                isotp_func_stack.process()
                response = isotp_func_stack.recv()
                if response is not None:
                    self._log(f"Received UDS functional response: {binascii.hexlify(response).decode('utf-8').upper()}")
                    return response
                time.sleep(0.001)
            self._log("UDS functional response timeout.")
            return None
        except Exception as e:
            self._log(f"Error sending/receiving UDS functional: {e}")
            return None

    def perform_ota_update(self, firmware_data):
        """执行完整的OTA更新流程"""
        self.ota_update_progress = 0.0
        
        self._log("Performing OTA update...")

        try:
            # Wake up ECU
            self.wakeup()
            time.sleep(0.1)
            self.wakeup()

            # 初始化地址和参数
            physical_addr = isotp.Address(txid=0x713, rxid=0x71B)
            functional_addr = isotp.Address(txid=0x7DF, rxid=0x71B)
            isotp_params = {'tx_data_min_length': 8, 'tx_padding': 0}

            isotp_physical_stack = isotp.CanStack(bus=self.canbus, address=physical_addr, params=isotp_params)
            isotp_functional_stack = isotp.CanStack(bus=self.canbus, address=functional_addr, params=isotp_params)

            # Step 1: 进入扩展会话模式
            if self.into_extended_session_mode(isotp_physical_stack, isotp_functional_stack, 0x03, "physical") != 0:
                self._log("Into extended session control failed")
                return False
            self._log("Into extended session control success")
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(10)

            # Step 2: 检查编程条件
            if self.check_programming_condition(isotp_physical_stack, 0xFF00, 0x01, None, 8)!= 0:
                    self._log("Check programming condition failed")
                    return False
            self._log("Check programming condition success")
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(10)

            # Step 3: 关闭DTC设置
            if self.control_DTC_setting(isotp_functional_stack, 0x82) != 0:
                self._log("Close DTC setting failed")
                # Functional timeout is acceptable for progress
            self._log("Close DTC setting success")
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(10)
 
            # Step 4: 关闭通信
            if self.control_communication(isotp_functional_stack, 0x83, 0x03) != 0:
                self._log("Close communication failed")
                # Functional timeout is acceptable for progress
            self._log("Close communication success")
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(10)

            # Step 5: 进入编程会话
            if self.into_programming_session_mode(isotp_physical_stack) != 0:
                self._log("Into programming session control failed")
                return False
            self._log("Into programming session control success")
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(10)

            # Step 6: MCU重启等待
            self._log("Waiting for the MCU to restart.....")
            self.testWaitForTimeout(3000)
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(10)

            # Step 7: 解锁安全访问
            if self.unlock_security_access(isotp_physical_stack, 0x11) != 0:
                self._log("Unlock security access failed")
                return False
            self._log("Unlock security access success")
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(10)

            # Step 8: 写入指纹数据
            if self.write_finger_print_data(isotp_physical_stack, 0xF184, 12) != 0:
                self._log("Write finger print data failed")
                return False
            self._log("Write finger print data success")
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(10)

            # Step 9: 擦除APP内存
            if self.erase_APP_memory(isotp_physical_stack) != 0:
                self._log("Erase APP memory failed")
                return False
            self._log("Erase APP memory success")
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(100)

            # Step 10: 请求下载
            if self.request_download(isotp_physical_stack, 0x44, len(firmware_data)) != 0:
                self._log("Request download failed")
                return False
            self._log("Request download success")
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(10)

            # Step 11: 数据传输
            block_size = 1024  # 每次传输1KB
            for i in range(0, len(firmware_data), block_size):
                block = firmware_data[i:i+block_size]
                if self.transfer_data(isotp_physical_stack, i//block_size + 1, block) != 0:
                    self._log("Transfer data failed")
                    return False
                self.testWaitForTimeout(0.1)  # 改为100微秒（0.1毫秒）
            
            self._log("Transfer data success")
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(10)

            # Step 12: 结束传输
            if self.exit_transfer(isotp_physical_stack) != 0:
                self._log("Exit transfer failed")
                return False
            self._log("Exit transfer success")
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(10)

            # Step 13: 校验内存完整性
            if self.check_memory_integrity(isotp_physical_stack) != 0:
                self._log("Check memory integrity failed")
                return False
            self._log("Check memory integrity success")
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(10)

            # Step 14: 请求固件结束
            if self.request_firmware_end(isotp_physical_stack, "success") != 0:
                self._log("Request firmware end failed")
                return False
            self._log("Request firmware end success")
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(10)

            # Step 15: ECU复位
            if self.ECU_reset(isotp_physical_stack, 0x01) != 0:
                self._log("ECU reset failed")
                return False
            self._log("ECU reset success")
            self.increase_progress()
            self.current_update_progress(self.ota_update_progress)
            self.testWaitForTimeout(10)

            self.current_update_progress(10)
            self._log("OTA update process completed successfully.")
            return True
        except Exception as e:
            self._log(f"OTA update exception: {str(e)}")
            return False

    def wakeup(self):
        message = can.Message(arbitration_id=0x33C, is_extended_id=False, data=[0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        self.canbus.send(message)

    def into_extended_session_mode(self, isotp_stack, isotp_func_stack, level, addressing_type):
        request_data = bytearray([0x10, 0x03 if addressing_type == "physical" else 0x83])
        if addressing_type == "physical":
            response = self.send_uds_request(isotp_stack, request_data, addressing_type)
        elif addressing_type == "functional":
            response = self.send_uds_request_functional(isotp_func_stack, request_data)
        else:
            return 1

        if response and response[0] == 0x50:
            return 0
        return 1

    def check_programming_condition(self, isotp_stack, did1, did2, rid_data_buffer, rid_data_len):        
        message = can.Message(arbitration_id=0x713, is_extended_id=False, data=[0x04, 0x31, 0x01, 0x02, 0x03, 0x00, 0x00, 0x00])
        self.canbus.send(message)
        response = self.send_uds_request(isotp_stack, message.data, "physical")
        if response and response[0] == 0x71:
            return 0
        return 1

    def control_DTC_setting(self, isotp_func_stack, sub_function):
        """控制DTC设置(85服务)"""
        request_data = bytearray([0x85, sub_function])
        response = self.send_uds_request(isotp_func_stack, request_data, "functional")
        if response and response[0] == 0xC5:
            self._log("DTC setting controlled successfully")
            return 0
        else:
            self._log("Failed to control DTC setting")
            return 1

    def control_communication(self, isotp_func_stack, channel, control_type):
        """控制通信(28服务)"""
        request_data = bytearray([0x28, channel, control_type])
        response = self.send_uds_request(isotp_func_stack, request_data, "functional")
        if response and response[0] == 0x68:
            self._log("Communication control successful")
            return 0
        else:
            self._log("Failed to control communication")
            return 1

    def into_programming_session_mode(self, isotp_stack):
        """发送UDS请求进入编程会话模式(10服务)"""
        request_data = bytearray([0x10, 0x02])  # 编程会话请求
        response = self.send_uds_request(isotp_stack, request_data, "physical")
        if response and response[0] == 0x50 and response[1] == 0x02:
            return 0  # 成功
        return 1  # 失败

    def unlock_security_access(self, isotp_physical_stack, level):
        """解锁安全访问(27服务) 使用uds_tester.py中的一致算法"""
        # 强制使用0x11子功能请求种子
        request_data = bytearray([0x27, 0x11])  # 固定子功能0x11
        response = self.send_uds_request(isotp_physical_stack, request_data, "physical")
        
        if response and response[0] == 0x67 and len(response) > 2:
            seed = response[2:]
            self._log(f"Received SEED: {binascii.hexlify(seed).decode('utf-8').upper()}")
            
            # 使用uds_tester.py中的安全算法
            key = calculate_key_from_seed(seed, level)
            self._log(f"Calculated key: {binascii.hexlify(key).decode('utf-8').upper()}")
            
            """ 
           # 强制使用0x12子功能发送密钥
            send_security_key_data = bytearray([0x06, 0x27, 0x12]) + key + bytearray([0x00])  # 固定子功能0x12

            # 直接发送原始CAN帧（显式指定ECU地址0x713）
            msg = can.Message(
                arbitration_id=0x713,
                data=bytes(send_security_key_data),
                is_extended_id=False
            )
            self.canbus.send(msg)
            self._log(f"Sent security key: {binascii.hexlify(bytes(send_security_key_data)).decode('utf-8').upper()}")
            """
            # 添加专用接收验证
            request_key = bytearray([0x27, 0x12]) + key
            response_key = self.send_uds_request(isotp_physical_stack, request_key, "physical")
            if response_key and response_key[0] == 0x67: # Positive response for 27
                return 0
            return 1
            

    def write_finger_print_data(self, isotp_physical_stack, Did, len_param):
        """根据uds_tester.py重构的指纹数据写入方法"""
        # 模拟默认指纹字符串
        finger_print_string_val = "ABCDEXY"  # 示例值，实际应从配置获取
        buf = bytearray(finger_print_string_val.encode('ascii'))
        buf.append(0x20)  # 添加终止符
        
        # 获取当前时间信息
        now = datetime.now()
        time_year_val = now.year - 2000  # 年份偏移
        time_month_val = now.month
        time_date_val = now.day
        
        # 构造请求数据
        request_data = bytearray([
            0x2E,  # WriteDataByIdentifier服务
            (Did >> 8) & 0xFF,  # DID高位
            Did & 0xFF,  # DID低位
            time_year_val & 0xFF,  # 年份偏移值
            time_month_val & 0xFF,  # 月份
            time_date_val & 0xFF  # 日期
        ])
        
        # 添加指纹字符串前6字节
        for i in range(6):
            request_data.append(buf[i] if i < len(buf) else 0x00)
        
        # 验证长度匹配
        if len(request_data) != len_param:
            self._log(f"Warning: 构造数据长度({len(request_data)})与预期({len_param})不匹配")
        
        # 发送请求
        response = self.send_uds_request(isotp_physical_stack, request_data, "physical")
        if response and response[0] == 0x6E:  # 正响应
            self._log("Fingerprint data written successfully")
            return 0
        
        self._log("Failed to write fingerprint data")
        return 1

    def erase_APP_memory(self, isotp_physical_stack):
        """
        Rewrites erase_APP_memory() based on the provided CAPL code.
        Performs memory erase using RoutineControl (0x31) for each app section.
        """
        rev_overall = 0 # Initialize overall return value

        for i in range(data_transfer_info.app_section):
            start_addr = data_transfer_info.app_start_addr[i][0]
            size = data_transfer_info.app_start_addr[i][1]

            # Construct erase_data as per CAPL: 4 bytes for address, 4 bytes for size
            erase_data_payload = bytearray([
                (start_addr >> 24) & 0xFF,
                (start_addr >> 16) & 0xFF,
                (start_addr >> 8) & 0xFF,
                start_addr & 0xFF,
                (size >> 24) & 0xFF,
                (size >> 16) & 0xFF,
                (size >> 8) & 0xFF,
                size & 0xFF
            ])
    
            request_data = bytearray([
                0x31,
                0x01,
                (0xFF00 >> 8) & 0xFF,  # RoutineIdentifier high byte
                0xFF00 & 0xFF          # RoutineIdentifier low byte
            ]) + erase_data_payload

            #DIAG_output_show(f"erase addr: {hex(start_addr)}, size: {size}")

            response = self.send_uds_request(isotp_physical_stack, request_data, "physical")
            if response is None or response[0] != 0x71: # Check for positive response to 0x31
                #DIAG_output_show(f"Erase APP memory failed for section {i}: No positive response or timeout.")
                rev_overall = 1 # Set overall return to error
                break # Exit loop on first error
            else:
                if len(response) < 5 or response[4] != 0x00:
                   # DIAG_output_show(f"Erase error for section {i}. Routine status: {response[4] if len(response) > 4 else 'N/A'}")
                    rev_overall = 1 # Set overall return to error
                    break # Exit loop on first error
                else:
                    break
                    #DIAG_output_show(f"Erase APP memory for section {i} successful.")
        return rev_overall
    def check_memory_integrity(self, isotp_physical_stack):
        """检查内存完整性(31服务)"""
        request_data = bytearray([0x31, 0x01, 0x02, 0x01])
        response = self.send_uds_request(isotp_physical_stack, request_data, "physical")
        if response and response[0] == 0x71 and len(response) >= 5 and response[4] == 0x00:
            self._log("Memory integrity check passed")
            return 0
        
        self._log("Memory integrity check failed")
        return 1

    def request_firmware_end(self, isotp_physical_stack, status="success"):
        """请求固件结束(36服务)"""
        # 根据实际情况修改，这是一个示例
        request_data = bytearray([0x36, 0x00])  # 示例数据
        response = self.send_uds_request(isotp_physical_stack, request_data, "physical")
        if response and response[0] == 0x7F and response[2] == 0x36:
            self._log("Firmware end requested successfully")
            return 0
        
        self._log("Failed to request firmware end")
        return 1

    def ECU_reset(self, isotp_physical_stack, reset_type=0x01):
        """ECU复位(11服务)"""
        request_data = bytearray([0x11, reset_type])
        response = self.send_uds_request(isotp_physical_stack, request_data, "physical")
        if response and response[0] == 0x51:
            self._log("ECU reset successful")
            return 0
        
        self._log("ECU reset failed")
        return 1
