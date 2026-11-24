# googletv.py
# Google TV (and Android TV) over the Android TV Remote protocol v2, the one
# Google's own remote apps use: a one-time pairing on port 6467 (the TV shows a
# code), then TLS connections on port 6466 that press keys and open app links
# such as https://www.netflix.com/title/<id>. Both ends identify themselves with
# certificates; the player's is made by tlskey.py. Messages are length-prefixed
# protobuf, built by hand here. The message layouts follow the androidtvremote2
# project's protocol files.
import binascii
import hashlib
import os
import socket
import sys
import time
import tlskey

try:
    import ssl
except ImportError:
    import ussl as ssl

PAIRING_PORT = 6467
REMOTE_PORT = 6466
CERT_FILE = "tv_cert.der" # The player's certificate and key, made once on the board
KEY_FILE = "tv_key.der"
CLIENT_NAME = "NFC Movie Player"
FEATURES = 622 # Remote features: keys, power, volume, app links
STATUS_OK = 200
KEY_POWER = 26
KEY_WAKEUP = 224
SHORT_PRESS = 3
MDNS_SERVICE = b"\x11_androidtvremote2\x04_tcp\x05local\x00"

# Protobuf

def _varint(n):
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)

def _field(number, value):
    """One protobuf field: an int as a varint, str or bytes (including nested messages) length-delimited."""
    if isinstance(value, int):
        return _varint(number << 3) + _varint(value)
    if isinstance(value, str):
        value = value.encode()
    return _varint(number << 3 | 2) + _varint(len(value)) + value

def _read_varint(data, i):
    n = shift = 0
    while True:
        b = data[i]
        i += 1
        n |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return n, i

def _decode(data):
    """A protobuf message as {field number: value}. Nested messages stay bytes."""
    fields, i = {}, 0
    while i < len(data):
        key, i = _read_varint(data, i)
        wire = key & 7
        if wire == 0:
            value, i = _read_varint(data, i)
        elif wire == 2:
            length, i = _read_varint(data, i)
            value, i = bytes(data[i:i + length]), i + length
        elif wire == 1:
            value, i = data[i:i + 8], i + 8
        elif wire == 5:
            value, i = data[i:i + 4], i + 4
        else:
            raise ValueError("Unreadable message from the TV")
        fields[key >> 3] = value
    return fields

# The player's certificate

_ready = False
_making = None # (steps, out) while the certificate is being made

def has_identity():
    global _ready
    if not _ready:
        try:
            os.stat(CERT_FILE)
            os.stat(KEY_FILE)
            _ready = True
        except OSError:
            pass
    return _ready

def make_identity_step():
    """Makes the player's certificate a little at a time; call it from the main loop.
    Returns True once the certificate exists."""
    global _making
    if has_identity():
        return True
    if not _making:
        print("Making the player's Google TV certificate (a minute or two, once)...")
        out = []
        _making = (tlskey.key_steps(out), out)
    steps, out = _making
    try:
        next(steps)
        return False
    except StopIteration:
        pass
    key = out[0]
    with open(KEY_FILE, "wb") as f:
        f.write(tlskey.private_key(key))
    with open(CERT_FILE + ".tmp", "wb") as f: # Written last and renamed, so a power cut can't leave half a certificate
        f.write(tlskey.certificate(key))
    os.rename(CERT_FILE + ".tmp", CERT_FILE)
    _making = None
    print("Google TV certificate ready.")
    return has_identity()

def _identity():
    with open(CERT_FILE, "rb") as f:
        cert = f.read()
    with open(KEY_FILE, "rb") as f:
        key = f.read()
    return cert, key

def _pem(label, der):
    body = binascii.b2a_base64(der).decode().replace("\n", "")
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n"

def _context():
    cert, key = _identity()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        ctx.check_hostname = False # CPython only
    except AttributeError:
        pass
    ctx.verify_mode = ssl.CERT_NONE # The TV's certificate is self-signed; pairing checks it instead
    if sys.implementation.name == "micropython":
        ctx.load_cert_chain(cert, key) # MicroPython takes DER bytes
    else: # Testing on a Mac: CPython wants PEM files
        with open("tv_cert.pem", "w") as f:
            f.write(_pem("CERTIFICATE", cert))
        with open("tv_key.pem", "w") as f:
            f.write(_pem("RSA PRIVATE KEY", key))
        ctx.load_cert_chain("tv_cert.pem", "tv_key.pem")
    return ctx

class Closed(Exception):
    """The TV hung up. (MicroPython has no ConnectionError.)"""

class _Link:
    """A TLS connection to the TV carrying length-prefixed protobuf messages."""

    def __init__(self, ip, port, timeout_s=8):
        self.raw = socket.socket()
        try:
            self.raw.settimeout(timeout_s)
            self.raw.connect(socket.getaddrinfo(ip, port)[0][-1])
            self.sock = _context().wrap_socket(self.raw)
        except Exception:
            self.raw.close()
            raise

    def timeout(self, seconds):
        try:
            self.sock.settimeout(seconds)
        except AttributeError: # MicroPython's TLS socket uses the plain socket's timeout
            self.raw.settimeout(seconds)

    def send(self, message):
        self.sock.write(_varint(len(message)) + message)

    def _read(self, n):
        data = b""
        while len(data) < n:
            chunk = self.sock.read(n - len(data))
            if not chunk:
                raise Closed("The TV closed the connection.")
            data += chunk
        return data

    def receive(self):
        length = shift = 0
        while True:
            b = self._read(1)[0]
            length |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                return _decode(self._read(length))

    def peer_certificate(self):
        return self.sock.getpeercert(True)

    def close(self):
        try:
            self.sock.close()
        except (OSError, AttributeError):
            pass

# Pairing

class Pairing:
    """Pairs the player with the TV: start() makes the TV show a 6-character code, finish(code) sends it back."""

    def __init__(self, ip):
        self.ip = ip
        self.link = None

    def _exchange(self, body):
        self.link.send(_field(1, 2) + _field(2, STATUS_OK) + body) # Protocol version 2, status OK
        reply = self.link.receive()
        if reply.get(2) != STATUS_OK:
            raise ValueError(f"The TV turned down the pairing (status {reply.get(2)}).")
        return reply

    def start(self):
        self.link = _Link(self.ip, PAIRING_PORT)
        try:
            self._exchange(_field(10, _field(1, "nfcmp") + _field(2, CLIENT_NAME))) # Pairing request
            hex6 = _field(1, 3) + _field(2, 6) # Encoding: hexadecimal, 6 symbols
            self._exchange(_field(20, _field(1, hex6) + _field(3, 1))) # Options: the player enters the code
            self._exchange(_field(30, _field(1, hex6) + _field(2, 1))) # Configuration; the TV now shows the code
        except Exception:
            self.close()
            raise

    def finish(self, code):
        """Sends the code shown on the TV. A typo raises ValueError and the pairing stays open for another try."""
        code = code.strip().upper()
        if len(code) != 6 or any(c not in "0123456789ABCDEF" for c in code):
            raise ValueError("The code is 6 letters and numbers, like 3F9A2C.")
        h = hashlib.sha256()
        for n in tlskey.public_key(_identity()[0]) + tlskey.public_key(self.link.peer_certificate()):
            h.update(tlskey.unsigned(n)) # Player's modulus and exponent, then the TV's
        h.update(binascii.unhexlify(code[2:]))
        secret = h.digest()
        if secret[0] != int(code[:2], 16): # The code's first byte checks the rest
            raise ValueError("That code doesn't match the one on the TV. Check it and try again.")
        try:
            self._exchange(_field(40, _field(1, secret)))
        finally:
            self.close()

    def is_open(self):
        return self.link is not None

    def close(self):
        if self.link:
            self.link.close()
            self.link = None

# Remote control

class Remote:
    """A remote-control connection. Answers the TV's setup messages, then sends keys and app links."""

    def __init__(self, ip):
        self.link = _Link(ip, REMOTE_PORT)
        self.on = None # Whether the screen is on, once the TV says
        try:
            while not self._handle(self.link.receive()):
                pass
            self.pump(1500, until_power_known=True)
        except Exception:
            self.close()
            raise

    def _handle(self, message):
        """Answers one message from the TV. Returns True once the TV says the connection is active."""
        if 1 in message: # Configure: answer with what this remote does
            device = _field(1, CLIENT_NAME) + _field(2, "NFCMP") + _field(3, 1) + _field(4, "1") + _field(5, "nfcmp") + _field(6, "1.0")
            self.link.send(_field(1, _field(1, FEATURES) + _field(2, device)))
        elif 2 in message: # Set active
            self.link.send(_field(2, _field(1, FEATURES)))
            return True
        elif 8 in message: # Ping
            self.link.send(_field(9, _field(1, _decode(message[8]).get(1, 0))))
        elif 40 in message: # Power state
            self.on = bool(_decode(message[40]).get(1))
        return False

    def pump(self, ms, until_power_known=False):
        """Answers the TV's messages (pings, power state) for up to ms."""
        deadline = time.ticks_add(time.ticks_ms(), ms)
        self.link.timeout(0.3)
        try:
            while time.ticks_diff(deadline, time.ticks_ms()) > 0:
                if until_power_known and self.on is not None:
                    return
                try:
                    self._handle(self.link.receive())
                except Closed:
                    raise
                except OSError: # Nothing to read yet
                    pass
        finally:
            self.link.timeout(8)

    def press(self, key):
        self.link.send(_field(10, _field(1, key) + _field(2, SHORT_PRESS)))

    def turn_on(self):
        """Wakes the TV. Returns True if it was off."""
        if self.on:
            return False
        self.press(KEY_POWER if self.on is False else KEY_WAKEUP) # Power toggles, so only when it's known to be off
        return True

    def open_link(self, link):
        self.link.send(_field(90, _field(1, link)))

    def close(self):
        self.link.close()

def wake(ip):
    remote = Remote(ip)
    try:
        if remote.turn_on():
            remote.pump(3000) # Wait for the TV to wake up
    finally:
        remote.close()

def open_link(ip, link):
    """Turns the TV on and opens an app link: a web URL the app handles, or market://launch?id=<package>."""
    remote = Remote(ip)
    try:
        if remote.turn_on():
            remote.pump(3000)
        remote.open_link(link)
        remote.pump(1000) # Give the TV a moment before hanging up
    finally:
        remote.close()

def _skip_name(data, i):
    while True:
        length = data[i]
        if length == 0:
            return i + 1
        if length & 0xC0 == 0xC0: # Compressed: a pointer ends the name
            return i + 2
        i += length + 1

def _tv_name(data):
    """The TV's name from an mDNS answer: the first label of its PTR record ("Living Room TV"), or None."""
    try:
        i = 12
        for _ in range(int.from_bytes(data[4:6], "big")): # Questions
            i = _skip_name(data, i) + 4
        for _ in range(int.from_bytes(data[6:8], "big")): # Answers
            i = _skip_name(data, i)
            kind, length = int.from_bytes(data[i:i + 2], "big"), int.from_bytes(data[i + 8:i + 10], "big")
            i += 10
            if kind == 12 and 0 < data[i] < 64:
                return bytes(data[i + 1:i + 1 + data[i]]).decode()
            i += length
    except (IndexError, UnicodeError):
        pass
    return None

def discover_all(timeout_ms=3000):
    """Every Google TV that answers an mDNS query: [{"kind", "name", "ip"}]."""
    # A one-shot query from a normal port: TVs answer straight back to it
    query = b"\x00\x01\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00" + MDNS_SERVICE + b"\x00\x0c\x80\x01"
    found = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout_ms / 1000)
        address = socket.getaddrinfo("224.0.0.251", 5353)[0][-1]
        for _ in range(2): # UDP can drop one, so ask twice
            sock.sendto(query, address)
        while True:
            data, addr = sock.recvfrom(1500)
            if b"_androidtvremote2" in data and all(tv["ip"] != addr[0] for tv in found):
                found.append({"kind": "googletv", "name": _tv_name(data) or "Google TV", "ip": addr[0]})
    except OSError:
        pass
    finally:
        sock.close()
    return found

def discover(timeout_ms=3000):
    """The first Google TV found, or None."""
    found = discover_all(timeout_ms)
    return found[0]["ip"] if found else None
