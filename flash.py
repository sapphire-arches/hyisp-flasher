import usb1
import sys
import time
from usb1 import REQUEST_TYPE_CLASS, RECIPIENT_INTERFACE, ENDPOINT_OUT, ENDPOINT_IN
from contextlib import AbstractContextManager
# import pdb

VENDOR_ID  = 0x0f39 # TG3 Electronics
PRODUCT_ID = 0x0000 # ISP
INTERFACE  = 0      # The only interface?

HID_INPUT_REPORT = 1
HID_OUTPUT_REPORT = 2
HID_FEATURE_REPORT = 3

def mk_packet(cmd, data):
    assert 0 <= cmd and cmd <= 0xff
    assert len(data) <= (255 - 2)

    packet_data = bytearray(4 + len(data))

    # declare this is a host -> device command
    packet_data[0] = 0xea

    # insert command and length
    packet_data[1] = len(data) + 2
    packet_data[2] = cmd

    # copy command data, computing parity as we go
    crc = 0xea ^ (len(data) + 2) ^ cmd
    for i, d in enumerate(data):
        packet_data[3 + i] = d
        crc = crc ^ d
    packet_data[3 + len(data)] = crc

    return packet_data

def swap_nybles(b):
    return ((b & 0x0f) << 4) | ((b & 0xf0) >> 4)

CMD_GET_FW_VERSION_ISP = 0xb0
CMD_GET_FW_VERSION_KBD = 0x4e
CMD_ENTER_ISP_MODE = 0x0a
CMD_ENTER_BL_ISP_MODE = 0xaa
CMD_RESET_CHIP = 0xaf
CMD_WRITE_BLOCK = 0xa1
CMD_ERASE_CHIP = 0xa4
CMD_GET_FW_PROFILE = 0xa5

class HyISP(AbstractContextManager):
    def __init__(self, context):
        self.handle = context.openByVendorIDAndProductID(VENDOR_ID, PRODUCT_ID)
        self.device = context.getByVendorIDAndProductID(VENDOR_ID, PRODUCT_ID)

        if self.handle is None or self.device is None:
            raise ValueError("Failed to find HyISP device")

        self.mps = self.device.getMaxPacketSize0()

    def __enter__(self):
        self._claim = self.handle.claimInterface(INTERFACE)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return self.handle.releaseInterface(INTERFACE)
        except usb1.USBErrorNoDevice:
            pass

    def _write(self, cmd, data=[]):
        packet = mk_packet(cmd, data)
        print('pkt:', packet.hex(':'))

        (n_reports, n_leftover)  = divmod(len(packet), (self.mps - 1))

        if n_leftover != 0:
            n_reports += 1

        for i in range(n_reports):
            idx = i * (self.mps - 1)
            if i == n_reports - 1:
                report_len = n_leftover + 1
            else:
                report_len = self.mps

            report = bytearray(report_len)
            report[0] = 0x1
            report[1:len(report)] = packet[idx:min(len(packet), idx + self.mps - 1)]

            print('->:', report.hex(':'))

            self.handle.controlWrite(
                # bmRequestType,
                ENDPOINT_OUT | REQUEST_TYPE_CLASS | 0b1,
                # bRequest (SET_REPORT),
                0x09,
                # wValue (report type / report ID)
                0x0301,
                # wIndex (interface)
                INTERFACE,
                # data
                report
            )

    def _read(self):
        data = self.handle.controlRead(
            # bmRequestType
            ENDPOINT_IN | REQUEST_TYPE_CLASS | 0b1,
            # bRequest
            0x01,   # GET_REPORT
            # wValue (report type/report ID)
            0x0301, # Feature report + 1 descriptor index
            # index
            INTERFACE,      # Interface 0
            # length
            self.mps,
        )

        if data[0] == 0xed:
            data = data[0:(data[1]+2)]

            crc = 0
            for b in data:
                crc = crc ^ b
            if crc != 0:
                raise ValueError("CRC failure: " + data.hex(':'))

            if data[2] == 0x00:
                raise ValueError("Error response: " + data.hex(':'))

            print('<-:', data.hex(':'))
            return data
        else:
            raise ValueError('malformed packet: ' + data.hex(':'))

    def get_isp_version(self):
        self._write(CMD_GET_FW_VERSION_ISP)
        data = self._read()

        return data[4]

    def get_kbd_version(self):
        self._write(CMD_GET_FW_VERSION_KBD)
        data = self._read()

        return data[4]

    def reset_chip(self):
        self._write(CMD_RESET_CHIP)
        data = self._read()

    def erase_chip(self):
        print('>erase chip')
        self._write(CMD_ERASE_CHIP)
        data = self._read()

        if data[3] != 0:
            raise ValueError('failed to erase chip')


    def enter_isp_mode(self):
        print('>enter isp mode')
        self._write(CMD_ENTER_ISP_MODE)
        data = self._read()

    def check_profile(self, profile):
        if len(profile) != 10:
            raise ValueError('profile should be length 10')
        # packet_data = [
        #     (0xff ^ swap_nybles(x)) for x in profile
        # ]
        self._write(CMD_GET_FW_PROFILE, profile)

        data = self._read()

    def upload_block(self, seqno, block):
        self._write(CMD_WRITE_BLOCK, bytes([
            (seqno >> 8) & 0xff,
            seqno & 0xff,
        ]) + block)

        data = self._read()
        if data[3] != 0:
            raise ValueError("Block upload failed")

with open('./2108S/L1943V18.bin', 'rb') as firmware_file:
    firmware_data = firmware_file.read()

with usb1.USBContext() as context:
    # context.setDebug(usb1.LOG_LEVEL_DEBUG)
    with HyISP(context) as isp:
        isp.handle.resetDevice()

        print('isp version:', isp.get_isp_version())
        print('kbd version:', isp.get_kbd_version())

        time.sleep(0.3)
        isp.reset_chip()
        time.sleep(0.3)

    # need to re-acquire the device since reset will disconnect it
    time.sleep(2)
    with HyISP(context) as isp:
        offset_base = len(firmware_data) - 14
        scrambled_header = firmware_data[offset_base:offset_base + 10]
        unscrambled_header = bytearray([(0xff ^ swap_nybles(x)) for x in scrambled_header])
        print("scrambled  :", scrambled_header.hex(':'))
        print("unscrambled:", unscrambled_header.hex(':'))
        print("unscrambled:", unscrambled_header)
        isp.check_profile(scrambled_header)

        isp.erase_chip()

        time.sleep(0.3)
        print('start firmware write:')
        block_size = 8
        total_block_count = (len(firmware_data) + block_size - 1) // block_size

        block_offset = 0x100

        block_count = 0x7f

        # it's not clear why this block is necessary, but the original flasher does it.
        for i in range(block_count):
            block_start = i * block_size + block_offset
            block = firmware_data[block_start:(block_start + block_size)]

            isp.upload_block(block_start, block)

            completion = int(100 * (i / block_count))

            print('#' * completion, ' ' * (100 - completion), f'{i:4d}/{block_count:4d} ({completion:3d}%)')

            # time.sleep(0.1)

        block_offset = 0
        block_count = total_block_count

        for i in range(block_count + 1):
            block_start = i * block_size + block_offset
            block = firmware_data[block_start:(block_start + block_size)]

            isp.upload_block(block_start, block)

            completion = int(100 * (i / block_count))

            print('#' * completion, ' ' * (100 - completion), f'{i:4d}/{block_count:4d} ({completion:3d}%)')

            # time.sleep(0.1)

        isp.reset_chip()
