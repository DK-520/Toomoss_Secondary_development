
from USBHandler import *

class CANController:
    def __init__(self, console: UDSConsole):
        self.console = console
        self.CANChannel = 0

    def init_can(self, dev_handle):
        CANConfig = CAN_INIT_CONFIG()
        CANConfig.CAN_Mode = 0x00
        CANConfig.CAN_ABOM = 0
        CANConfig.CAN_NART = 1
        CANConfig.CAN_RFLM = 0
        CANConfig.CAN_TXFP = 1
        CANConfig.CAN_BRP_CFG3 = 4
        CANConfig.CAN_BS1_CFG1 = 16
        CANConfig.CAN_BS2_CFG2 = 4
        CANConfig.CAN_SJW = 1

        ret = CAN_Init(dev_handle, self.CANChannel, byref(CANConfig))
        if ret == CAN_SUCCESS:
            self.console.info("CAN通道初始化成功")
            return True
        else:
            self.console.error("CAN通道初始化失败")
            return False
