# HYUSB firmware updater

This is a pure python implementation (using `libusb`) of the TG3 Electronics
HYISP firmware updater `USB_FD.exe`. This is useful for flashing old Ducky
keyboards like the Ducky Zero (2108S) on Linux since the official firmware
update tool uses the Windows HID interfaces. The controller does not offer
non-control endpoints so the Linux HID driver doesn't create a HIDRAW device for
it, meaning WINE can't expose the HID interface to the software.
the software.

If you have a 2108S that has the "flashing lock key" problem, just download the
firmware from the [Ducky archive site](https://old.duckychannel.com.tw/en/firmware_updater.html).
(n.b. at time of writting the links are broken, but if nothing else it should
let you know what zip file to trawl the internet for.) Other HYUSB based
products can probably use this code, but I only wrote it for the 2108S.

# Protocol description
The protocol consists of a request/acknowledge system over HID
`{SET,GET}_REPORT` on the control channel. The basic format of the packets is as
follows:

## Flash flow
At a high level, the flash flow is:
1. Reset the device.
2. Validate that the profile of the device and the firmware file match.
3. Issue a chip erase.
4. Write all the data blocks
5. Reset the chip back to user mode.

### Profile validation

## Command description
Host to device (via `SET_REPORT`):

```
01 ea xx yy .... pp
|  |  |  |  |    \_ xor parity over all the bytes, starting at 0xEA
|  |  |  |  \______ data (may be 0-length)
|  |  |  \_________ command code (see below)
|  |  \____________ length in bytes (starting at this field, so len(...) + 2)
|  \_______________ constant, host-to-device direction specifier
\__________________ constant. Unclear what other values mean
```

If the request size exceeds the maximum packet size reported on the interface,
the request is just sent in 2 (or more, though the official updater never uses
more than 2 and it's unclear if this works) separate `SET_REPORT` transactions
with no additional framing.

Device to host (via `GET_REPORT`):

```
ed xx yy zz .. pp
|  |  |  |  |  \_ xor parity over all the bytes, starting at 0xEA
|  |  |  |  \____ data (will always contain at least 1 byte)
|  |  |  \_______ reply status code
|  |  \__________ command code (see below, will match what the host sent)
|  \_____________ length in bytes (starting at this field, so len(...) + 2)
\________________ constant, device-to-host direction specifier
```

The reply status is `0x00` for success and in the range `0xE0-0xEF` for failure.

| Command Code | Action |
| ------------ | ------ |
| `0x0a` | Enter ISP mode |
| `0x4e` | Get Application (keyboard) firmware version |
| `0xa1` | Write data block |
| `0xa4` | Erase application program flash |
| `0xa5` | Get firmware profile |
| `0xaa` | Enter bootloader ISP mode (DANGER) |
| `0xaf` | Reset the chip |
| `0xb0` | Get ISP firmware version |

### Enter ISP Mode
No data bytes in request or response. Just puts the keyboard into ISP mode.

### Get application firmware version
No data bytes in request. Reply has 1 data byte, the firmware version.
I think this just reads some configuration flash byte. Not actually used
anywhere in the flash flow.

### Write data block
Up to 10 data bytes in request:
  - Data byte 0 is the MSB of the offset (in bytes) to write.
  - Data byte 1 is the LSB of the offset (in bytes) to write.
  - Data bytes 2-9 are the actual bytes to write.
Response has only the standard reply status code.

### Erase application program flash
No data bytes in the request or response.

### Get firmware profile
This is a bit of a weird one. The profile is stored in 10 bytes, 14 bytes from
the end of the firmware file. To construct the profile to send, those 10 bytes
must be extracted and then have the formula `~((x >> 4) | (x << 4))` applied to
them (i.e. swap the nybbles and bitwise invert). These 10 bytes are then the
data bytes of the "check profile" request. The firmware will then send the usual
status code back, indicating if the profile matched or not.

### Enter bootloader ISP mode
Based on the updater binary, this takes and receives no data bytes. However, I
think this has a risk of bricking the device to the point of requiring soldering
to the in-circuit debug connectors and I didn't want to risk that, so this is
completely untested.

### Reset the chip
No in or out data bytes.
Causes the chip to reset (I think it hits the reset vector, though it could just
be a USB bus reset).

### Get ISP Firmware Version
Same as "get application firmware version", this takes no data and returns 1
byte representing the ISP firmware version.
