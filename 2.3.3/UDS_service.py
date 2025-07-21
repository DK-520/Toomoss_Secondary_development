
from usb2can import *
from usb2lin import *
from usb_device import *
import time
from time import sleep
from ctypes import *

PHYSICAL_ADDRESSING_ID = 0x7DF
FUNCTIONAL_ADDRESSING_ID = 0x713

addressing_type = 'physical'  # 'physical' or 'functional'
if addressing_type == 'physical':
    CAN_ID = PHYSICAL_ADDRESSING_ID
else:
    CAN_ID = FUNCTIONAL_ADDRESSING_ID

def request_download(device_handle, can_channel, memory_address, length):
    """
    发起 UDS 0x34 请求下载服务
    """
    msg = CAN_MSG()
    msg.ID = CAN_ID
    msg.DataLen = 8
    msg.Data[0] = 0x04  # 数据长度（不包含长度自身）
    msg.Data[1] = 0x34  # UDS 服务 ID
    msg.Data[2] = 0x44  # 模式（Download to ECU）

    # 内存地址（假设为 32-bit 地址）
    msg.Data[3] = (memory_address >> 24) & 0xFF
    msg.Data[4] = (memory_address >> 16) & 0xFF
    msg.Data[5] = (memory_address >> 8) & 0xFF
    msg.Data[6] = memory_address & 0xFF

    # 数据长度
    msg.Data[7] = length & 0xFF

    # 填充剩余字节为0
    for i in range(8):
        if i > 7:
            msg.Data[i] = 0x00

    ret = CAN_SendMsg(device_handle, can_channel, byref(msg), 1)
    if ret < 0:
        print("发送请求下载失败！")
        return False
    sleep(0.5)

    # 接收响应
    CanMsgBuffer = (CAN_MSG * 1024)()
    CanNum = CAN_GetMsg(device_handle, can_channel, byref(CanMsgBuffer))
    if CanNum > 0 and CanMsgBuffer[0].Data[1] == 0x7F:
        print("NRC 错误:", hex(CanMsgBuffer[0].Data[3]))
        return False
    return True

def transfer_data(device_handle, can_channel, block_sequence_counter, data_block):
    """
    发送 UDS 0x36 传输数据块（支持多帧传输）
    """
    block_size = len(data_block)
    max_data_per_frame = 7  # 单帧最多 7 字节数据

    # === 首帧 FF ===
    first_frame = CAN_MSG()
    first_frame.ID = 0x7DF
    first_frame.DataLen = 8  # 固定为 8 字节
    first_frame.Data[0] = 0x10 | ((block_size >> 8) & 0x0F)  # FF 帧头 + 高位长度
    first_frame.Data[1] = block_size & 0xFF                  # 低位长度
    first_frame.Data[2] = 0x36                               # UDS 服务码
    first_frame.Data[3] = block_sequence_counter             # 块序号

    # 填充剩余字节为0
    for i in range(4, 8):
        first_frame.Data[i] = 0x00

    # 填充首帧剩余空间（最多放 4 字节数据）
    offset = 0
    for i in range(4):
        if offset + i < block_size:
            first_frame.Data[4 + i] = data_block[offset + i]
        else:
            break

    ret = CAN_SendMsg(device_handle, can_channel, byref(first_frame), 1)
    if ret < 0:
        print("发送首帧失败！")
        return False

    offset += 4  # 已发送 4 字节
    cf_index = 1  # 连续帧索引（1~F）

    # === 连续帧 CF ===
    while offset < block_size:
        cf = CAN_MSG()
        cf.ID = 0x7DF
        cf.DataLen = 8
        cf.Data[0] = 0x20 | (cf_index & 0x0F)  # CF 帧头

        # 填入最多 7 字节数据
        for i in range(7):
            if offset + i < block_size:
                cf.Data[1 + i] = data_block[offset + i]
            else:
                break

        ret = CAN_SendMsg(device_handle, can_channel, byref(cf), 1)
        if ret < 0:
            print("发送连续帧失败！")
            return False

        offset += 7
        cf_index = (cf_index + 1) % 16  # 索引循环使用 0~F

    return True

def request_transfer_exit(device_handle, can_channel):
    """
    发送 UDS 0x37 请求退出传输
    """
    msg = CAN_MSG()
    msg.ID = 0x7DF
    msg.DataLen = 8
    msg.Data[0] = 0x01
    msg.Data[1] = 0x37
    for i in range(2, 8):
        msg.Data[i] = 0x00  # 填充剩余字节
    ret = CAN_SendMsg(device_handle, can_channel, byref(msg), 1)
    if ret < 0:
        print("发送退出传输失败！")
        return False
    return True

def receive_can_message(device_handle, can_channel):
    """
    接收CAN消息
    :param device_handle: 设备句柄
    :param can_channel: CAN通道
    :return: 接收到的消息
    """
    CanMsgBuffer = (CAN_MSG * 1024)()
    CanNum = CAN_GetMsg(device_handle, can_channel, byref(CanMsgBuffer))
    if CanNum > 0:
        for i in range(CanNum):
            print(f"Received message ID: {CanMsgBuffer[i].ID}")
            print(f"Data: {[hex(CanMsgBuffer[i].Data[j]) for j in range(CanMsgBuffer[i].DataLen)]}")
    elif CanNum == 0:
        print("No message received.")
    else:
        print("Error receiving message.")


def send_diagnostic_session_control(device_handle, can_channel, session_type=0x01, addressing_type='physical', console=None):
    """
    发送诊断会话控制请求   0x10
    addressing_type: 'physical' 物理寻址(默认), 'functional' 功能寻址
    """
    msg = CAN_MSG()
    # 根据寻址类型选择CAN ID
    msg.ID = PHYSICAL_ADDRESSING_ID if addressing_type == 'physical' else FUNCTIONAL_ADDRESSING_ID
    msg.DataLen = 8  # 固定为8字节
    msg.Data[0] = 0x02  # 数据长度
    msg.Data[1] = 0x10  # UDS服务ID
    msg.Data[2] = session_type  # 会话类型
    for i in range(3, 8):
        msg.Data[i] = 0x00  # 填充剩余字节

    ret = CAN_SendMsg(device_handle, can_channel, byref(msg), 1)
    if ret < 0:
        if console: console.error("发送诊断会话控制失败")
        return False
    else:
        timeout = 1.0  # 统一超时时间为1秒
    if console: console.debug(f"发送诊断会话控制成功，会话类型: {hex(session_type)}，超时: {timeout}秒，等待响应...")

    # 修改为循环接收响应，增加超时机制
    start_time = time.time()
    # 统一超时时间为1秒
    timeout = 1.0
    success = False
    while time.time() - start_time < timeout:
        CanMsgBuffer = (CAN_MSG * 1024)()
        CanNum = CAN_GetMsg(device_handle, can_channel, byref(CanMsgBuffer))
        if CanNum > 0:
            for i in range(CanNum):
                response = CanMsgBuffer[i]
                data = [response.Data[j] for j in range(response.DataLen)]
                if console: 
                    console.debug(f"收到响应 ID: {hex(response.ID)}，数据: {[hex(x) for x in data]}")
                # 根据寻址类型验证响应ID
                # 原物理寻址响应ID逻辑，可根据实际情况调整
                expected_physical_id = msg.ID + 0x8  
                # 原功能寻址响应ID范围，可根据实际情况调整
                functional_id_range = range(0x7E8, 0x7F0) 

                # 新增配置项，可在文件开头定义全局变量，这里为示例方便直接写在此处
                CUSTOM_PHYSICAL_RESPONSE_IDS = [0x3c1]  # 可根据实际情况添加更多ID
                CUSTOM_FUNCTIONAL_RESPONSE_IDS = []  

                is_valid_id = (
                    (addressing_type == 'physical' and (response.ID == expected_physical_id or response.ID in CUSTOM_PHYSICAL_RESPONSE_IDS)) or 
                    (addressing_type == 'functional' and (response.ID in functional_id_range or response.ID in CUSTOM_FUNCTIONAL_RESPONSE_IDS))
                )
                # 详细日志：记录响应ID验证状态
                if console: 
                    console.debug(f"响应ID验证: 寻址类型={addressing_type}, 预期物理ID={hex(expected_physical_id)}, 实际ID={hex(response.ID)}, 有效={is_valid_id}")
                if is_valid_id:
                    # 检查正响应 (50 + 会话类型)
                    if len(data) >= 3 and data[1] == 0x50 and data[2] == session_type:
                        success = True
                        if console: console.debug("诊断会话控制成功")
                        return success
                    # 检查负响应 (7F + 服务ID + NRC)
                    elif len(data) >= 4 and data[1] == 0x7F and data[2] == 0x10:
                        nrc = data[3]
                        if console: console.error(f"诊断会话控制失败，NRC: {hex(nrc)}")
                        # 物理寻址时收到负响应立即返回失败
                        if addressing_type == 'physical':
                            return False
                        # 功能寻址时继续等待其他ECU响应
                        continue
                        # 功能寻址继续等待其他ECU响应
        # 固定轮询间隔为0.1秒
        time.sleep(0.1)
        remaining_time = timeout - (time.time() - start_time)
        if console: console.debug(f"等待响应中，剩余时间: {remaining_time:.2f}秒")
    if console: console.error("诊断会话控制超时未收到响应")
    return success


def request_security_access(device_handle, can_channel, level=0x01, console=None):
    """
    请求安全访问  0x27
    """
    msg = CAN_MSG()
    msg.ID = 0x7DF
    msg.DataLen = 8
    msg.Data[0] = 0x02   # 数据长度
    msg.Data[1] = 0x27   # UDS服务ID
    msg.Data[2] = level  # 安全等级
    for i in range(3, 8):  # 填充剩余5字节为0
        msg.Data[i] = 0x00
    ret = CAN_SendMsg(device_handle, can_channel, byref(msg), 1)
    if ret < 0:
        if console: console.error("请求安全访问失败！")
        return False

    sleep(0.5)  # 等待响应
    CanMsgBuffer = (CAN_MSG * 1024)()
    CanNum = CAN_GetMsg(device_handle, can_channel, byref(CanMsgBuffer))
    if CanNum > 0:
        for i in range(CanNum):
            data = [CanMsgBuffer[i].Data[j] for j in range(CanMsgBuffer[i].DataLen)]
            if console:
                console.debug(f"收到响应 ID: {hex(CanMsgBuffer[i].ID)}")
                console.debug(f"数据内容: {[hex(x) for x in data]}")
            if data[1] == 0x7F and data[2] == 0x27:
                nrc = data[3]
                if console: console.debug(f"NRC 错误码: {hex(nrc)}")
                return False
            elif len(data) > 2 and data[1] == 0x67 and data[2] == level:
                seed = data[3:] if len(data) > 3 else []
                if console: 
                    console.debug(f"收到种子: {[hex(x) for x in seed]}")
                    console.debug(f"种子长度: {len(seed)}字节")
                return seed  # 返回种子数据
            elif len(data) > 1 and data[1] == 0x7F:
                if console: console.warning(f"收到NRC错误响应: {[hex(x) for x in data]}")
                return False
    else:
        if console: console.debug("未收到有效响应")
    return None


def send_security_key(device_handle, can_channel, level, key, console=None):
    """
    发送安全访问密钥
    """
    msg = CAN_MSG()
    msg.ID = 0x7DF
    msg.DataLen = 8
    msg.Data[0] = 0x02 + len(key)  # 数据长度
    msg.Data[1] = 0x27             # UDS服务ID
    msg.Data[2] = level | 0x01     # 响应子功能，+1 表示发送密钥
    for i in range(len(key)):
        msg.Data[3 + i] = key[i]
    
    # 填充剩余字节为0
    for i in range(3 + len(key), 8):
        msg.Data[i] = 0x00
    ret = CAN_SendMsg(device_handle, can_channel, byref(msg), 1)
    if ret < 0:
        print("发送密钥失败！")
        return False

    sleep(0.5)
    CanMsgBuffer = (CAN_MSG * 1024)()
    CanNum = CAN_GetMsg(device_handle, can_channel, byref(CanMsgBuffer))
    if CanNum > 0:
        for i in range(CanNum):
            data = [CanMsgBuffer[i].Data[j] for j in range(CanMsgBuffer[i].DataLen)]
            if console:
                console.debug(f"收到响应 ID: {hex(CanMsgBuffer[i].ID)}")
                console.debug(f"数据内容: {[hex(x) for x in data]}")

            if data[1] == 0x7F and data[2] == 0x27:
                nrc = data[3]
                if console: console.debug(f"NRC 错误码: {hex(nrc)}")
                return False
            elif data[1] == 0x67 and (data[2] & 0xFE) == (level | 0x01):
                if console: console.debug("密钥验证成功")
                return True
    else:
        if console: console.debug("未收到响应")
    return False

def read_data_by_identifier(device_handle, can_channel, did=0xF190, console=None):
    """
    发送 UDS 0x22 服务，读取指定 DID 数据
    :param device_handle: 设备句柄
    :param can_channel: CAN通道
    :param did: 要读取的 DID
    """
    msg = CAN_MSG()
    msg.ID = 0x7DF
    msg.DataLen = 8
    msg.Data[0] = 0x04
    msg.Data[1] = 0x22
    msg.Data[2] = (did >> 8) & 0xFF
    msg.Data[3] = did & 0xFF
    for i in range(4, 8):
        msg.Data[i] = 0x00

    ret = CAN_SendMsg(device_handle, can_channel, byref(msg), 1)
    if ret < 0:
        print("Read data by identifier failed!")
        return False

    sleep(0.5)
    CanMsgBuffer = (CAN_MSG * 1024)()
    CanNum = CAN_GetMsg(device_handle, can_channel, byref(CanMsgBuffer))

    if CanNum > 0:
        for i in range(CanNum):
            data = [CanMsgBuffer[i].Data[j] for j in range(CanMsgBuffer[i].DataLen)]
            if console: console.debug(f"收到响应 ID={hex(CanMsgBuffer[i].ID)}，数据={[hex(x) for x in data]}")
    else:
        if console: console.debug("未收到响应")

    return True


def control_dtc_setting(device_handle, can_channel, sub_function, addressing_type='functional', console=None):
    """控制DTC设置(85服务)"""
    if console: console.debug(f"控制DTC设置: 子功能0x{sub_function:02X}")
    msg = CAN_MSG()
    msg.ID = 0x7DF
    msg.DataLen = 8
    msg.Data[0] = 0x02
    msg.Data[1] = 0x85
    msg.Data[2] = sub_function
    for i in range(3, 8):
        msg.Data[i] = 0x00

    ret = CAN_SendMsg(device_handle, can_channel, byref(msg), 1)
    if ret != 0:
        if console: console.error("发送DTC控制请求失败")
        return False

    # 等待响应
    import time
    start_time = time.time()
    timeout = 2.0
    while time.time() - start_time < timeout:
        CanMsgBuffer = (CAN_MSG * 1024)()
        CanNum = CAN_GetMsg(device_handle, can_channel, byref(CanMsgBuffer))
        if CanNum > 0:
            for i in range(CanNum):
                response = CanMsgBuffer[i]
                if response.ID == 0x71b:
                    data = [response.Data[j] for j in range(response.DataLen)]
                    if data[1] == 0xC5:  # 85服务正响应
                        return True
        time.sleep(0.1)
    return False


def control_communication(device_handle, can_channel, channel, control_type, addressing_type='functional', console=None):
    """控制通信(28服务)"""
    if console: console.debug(f"控制通信: 通道0x{channel:02X}, 类型0x{control_type:02X}")
    msg = CAN_MSG()
    msg.ID = 0x7DF if addressing_type == 'functional' else 0x713
    msg.DataLen = 8
    msg.Data[0] = 0x03
    msg.Data[1] = 0x28
    msg.Data[2] = channel
    msg.Data[3] = control_type
    for i in range(4, 8):
        msg.Data[i] = 0x00

    ret = CAN_SendMsg(device_handle, can_channel, byref(msg), 1)
    if ret != 0:
        if console: console.error("发送通信控制请求失败")
        return False

    # 等待响应
    import time
    start_time = time.time()
    timeout = 2.0
    while time.time() - start_time < timeout:
        CanMsgBuffer = (CAN_MSG * 1024)()
        CanNum = CAN_GetMsg(device_handle, can_channel, byref(CanMsgBuffer))
        if CanNum > 0:
            for i in range(CanNum):
                response = CanMsgBuffer[i]
                if response.ID == 0x71b:
                    data = [response.Data[j] for j in range(response.DataLen)]
                    if data[1] == 0x68:  # 28服务正响应
                        return True
        time.sleep(0.1)
    return False


def check_memory_integrity(device_handle, can_channel, console=None):
    """检查内存完整性(31服务)"""
    if console: console.debug("检查内存完整性...")
    msg = CAN_MSG()
    msg.ID = 0x713
    msg.DataLen = 8
    msg.Data[0] = 0x04
    msg.Data[1] = 0x31
    msg.Data[2] = 0x01
    msg.Data[3] = 0x02
    msg.Data[4] = 0x03
    for i in range(5, 8):
        msg.Data[i] = 0x00

    ret = CAN_SendMsg(device_handle, can_channel, byref(msg), 1)
    if ret != 0:
        if console: console.error("发送内存完整性检查请求失败")
        return False

    # 等待响应
    import time
    start_time = time.time()
    timeout = 1.0
    while time.time() - start_time < timeout:
        CanMsgBuffer = (CAN_MSG * 1024)()
        CanNum = CAN_GetMsg(device_handle, can_channel, byref(CanMsgBuffer))
        if CanNum > 0:
            for i in range(CanNum):
                response = CanMsgBuffer[i]
                if response.ID == 0x71b:
                    data = [response.Data[j] for j in range(response.DataLen)]
                    if data[1] == 0x71 and data[4] == 0x00:  # 31服务正响应且状态成功
                        return 0
        time.sleep(0.1)
    return 1


def ecu_reset(device_handle, can_channel, reset_type=0x01, console=None):
    """ECU重置(11服务)"""
    if console: console.debug(f"执行ECU重置: 类型0x{reset_type:02X}")
    msg = CAN_MSG()
    msg.ID = 0x713
    msg.DataLen = 8
    msg.Data[0] = 0x02
    msg.Data[1] = 0x11
    msg.Data[2] = reset_type
    for i in range(3, 8):
        msg.Data[i] = 0x00

    ret = CAN_SendMsg(device_handle, can_channel, byref(msg), 1)
    if ret != 0:
        if console: console.error("发送ECU重置请求失败")
        return False

    # 等待响应
    import time
    start_time = time.time()
    timeout = 1.0
    while time.time() - start_time < timeout:
        CanMsgBuffer = (CAN_MSG * 1024)()
        CanNum = CAN_GetMsg(device_handle, can_channel, byref(CanMsgBuffer))
        if CanNum > 0:
            for i in range(CanNum):
                response = CanMsgBuffer[i]
                if response.ID == 0x71b:
                    data = [response.Data[j] for j in range(response.DataLen)]
                    if data[1] == 0x51:  # 11服务正响应
                        return True
        time.sleep(0.1)
    return False


def enter_default_session(device_handle, can_channel, addressing_type='functional', console=None):
    """进入默认会话(10服务)"""
    if console: console.debug("进入默认会话...")
    msg = CAN_MSG()
    msg.ID = 0x7DF if addressing_type == 'functional' else 0x713
    msg.DataLen = 8
    msg.Data[0] = 0x02
    msg.Data[1] = 0x10
    msg.Data[2] = 0x01 if addressing_type == 'physical' else 0x81

    for i in range(3, 8):
        msg.Data[i] = 0x00

    ret = CAN_SendMsg(device_handle, can_channel, byref(msg), 1)
    if ret != 0:
        if console: console.error("发送默认会话请求失败")
        return False

    # 等待响应
    import time
    start_time = time.time()
    timeout = 0.01
    while time.time() - start_time < timeout:
        CanMsgBuffer = (CAN_MSG * 1024)()
        CanNum = CAN_GetMsg(device_handle, can_channel, byref(CanMsgBuffer))
        if CanNum > 0:
            for i in range(CanNum):
                response = CanMsgBuffer[i]
                if response.ID == 0x71b:
                    data = [response.Data[j] for j in range(response.DataLen)]
                    if data[1] == 0x50:  # 10服务正响应
                        return True
        time.sleep(0.1)
    return False

def read_data_by_identifier(device_handle, can_channel, did=0xF190, console=None):
    """
    发送 UDS 0x22 服务，读取指定 DID 数据
    :param device_handle: 设备句柄
    :param can_channel: CAN通道
    :param did: 要读取的 DID
    """
    msg = CAN_MSG()
    msg.ID = 0x7DF
    msg.DataLen = 8
    msg.Data[0] = 0x04
    msg.Data[1] = 0x22
    msg.Data[2] = (did >> 8) & 0xFF
    msg.Data[3] = did & 0xFF
    for i in range(4, 8):
        msg.Data[i] = 0x00

    ret = CAN_SendMsg(device_handle, can_channel, byref(msg), 1)
    if ret < 0:
        print("Read data by identifier failed!")
        return False

    sleep(0.5)
    CanMsgBuffer = (CAN_MSG * 1024)()
    CanNum = CAN_GetMsg(device_handle, can_channel, byref(CanMsgBuffer))

    if CanNum > 0:
        for i in range(CanNum):
            data = [CanMsgBuffer[i].Data[j] for j in range(CanMsgBuffer[i].DataLen)]
            if console: console.debug(f"收到响应 ID={hex(CanMsgBuffer[i].ID)}，数据={[hex(x) for x in data]}")
    else:
        if console: console.debug("未收到响应")

    return True


def read_ecu_version(device_handle, can_channel, console=None):
    """
    快捷函数：读取 ECU 版本号（DID=0xF190）
    """
    result = read_data_by_identifier(device_handle, can_channel, 0xF190)
    if result and console:
        console.log("ECU 版本号请求已发送")
    return result

