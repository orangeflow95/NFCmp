# pn532.py
# Minimal PN532 driver over I2C: just enough to read a card's UID.
import time

_ADDR = 0x24
_HOST_TO_PN532 = 0xD4
_PN532_TO_HOST = 0xD5
_ACK = b"\x00\x00\xff\x00\xff\x00"

_CMD_GET_FIRMWARE_VERSION = 0x02
_CMD_SAM_CONFIGURATION = 0x14
_CMD_RF_CONFIGURATION = 0x32
_CMD_IN_LIST_PASSIVE_TARGET = 0x4A

class PN532:
    def __init__(self, i2c, addr=_ADDR):
        self.i2c = i2c
        self.addr = addr
        # The PN532 can ignore the first few messages while it wakes up
        for _ in range(10):
            try:
                ic, ver, rev, _support = self._call(_CMD_GET_FIRMWARE_VERSION)
                self.firmware = f"PN5{ic:02x} v{ver}.{rev}"
                break
            except (OSError, RuntimeError):
                time.sleep_ms(100)
        else:
            raise RuntimeError("PN532 not found. Check the wiring and that the board's switches are set to I2C.")

        self._call(_CMD_SAM_CONFIGURATION, b"\x01\x14\x01") # Normal mode
        # Look for a card a couple of times, then report "no card" instead of waiting forever
        self._call(_CMD_RF_CONFIGURATION, b"\x05\xff\x01\x02")

    def read_uid(self):
        """Returns the UID of a card on the reader as a hex string, or None."""
        try:
            data = self._call(_CMD_IN_LIST_PASSIVE_TARGET, b"\x01\x00") # 1 card, ISO14443A
        except (OSError, RuntimeError):
            return None
        if len(data) < 6 or data[0] == 0:
            return None
        uid_len = data[5]
        return "".join(f"{b:02X}" for b in data[6:6 + uid_len])

    def _call(self, cmd, params=b"", timeout_ms=1000):
        """Sends a command and returns the response data."""
        body = bytes([_HOST_TO_PN532, cmd]) + params
        frame = bytearray(b"\x00\x00\xff")
        frame.append(len(body))
        frame.append(-len(body) & 0xFF)
        frame.extend(body)
        frame.append(-sum(body) & 0xFF)
        frame.append(0x00)
        self.i2c.writeto(self.addr, frame)

        if not self._wait_ready(timeout_ms) or self._read(len(_ACK)) != _ACK:
            raise RuntimeError("PN532 did not acknowledge command")
        if not self._wait_ready(timeout_ms):
            raise RuntimeError("PN532 response timed out")

        # Response frame: 00 00 FF LEN LCS D5 CMD+1 DATA... DCS 00
        resp = self._read(32)
        i = resp.find(b"\x00\xff")
        if i < 0 or i + 4 >= len(resp):
            raise RuntimeError("PN532 sent a bad frame")
        length = resp[i + 2]
        if (length + resp[i + 3]) & 0xFF or i + 5 + length > len(resp):
            raise RuntimeError("PN532 sent a bad frame length")
        body = resp[i + 4:i + 4 + length]
        if (sum(body) + resp[i + 4 + length]) & 0xFF:
            raise RuntimeError("PN532 sent a bad checksum")
        if body[0] != _PN532_TO_HOST or body[1] != cmd + 1:
            raise RuntimeError("PN532 sent an unexpected response")
        return body[2:]

    def _wait_ready(self, timeout_ms):
        """Polls the status byte until the PN532 has data for us."""
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
            try:
                if self.i2c.readfrom(self.addr, 1)[0] & 0x01:
                    return True
            except OSError:
                pass # The PN532 doesn't answer on I2C while it's busy
            time.sleep_ms(10)
        return False

    def _read(self, n):
        # Every I2C read starts with a status byte, so skip it
        return self.i2c.readfrom(self.addr, n + 1)[1:]
