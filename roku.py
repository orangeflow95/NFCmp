# roku.py
# Roku TVs and players over Roku's External Control Protocol (ECP): plain HTTP on port 8060.
import socket
import time

try:
    import requests
except ImportError:
    import urequests as requests

def _post(ip, path):
    r = requests.post(f"http://{ip}:8060/{path}", headers={"Content-Length": "0"}, timeout=5)
    r.close()

def wake(ip):
    _post(ip, "keypress/PowerOn")
    time.sleep(3) # Wait for the TV to wake up

def play(ip, app_id, content_id, media_type):
    """Turns the TV on and deep links the app straight into the title."""
    wake(ip)
    _post(ip, f"launch/{app_id}?contentId={content_id}&mediaType={media_type}")

def _name(ip):
    """The name the Roku was given ("Living Room Roku"), or None."""
    try:
        r = requests.get(f"http://{ip}:8060/query/device-info", timeout=3)
        try:
            info = r.text
        finally:
            r.close()
    except Exception:
        return None
    for tag in ("user-device-name", "friendly-device-name", "friendly-model-name"):
        start = info.find(f"<{tag}>")
        if start >= 0:
            name = info[start + len(tag) + 2:info.find(f"</{tag}>", start)].strip()
            if name:
                return name.replace("&amp;", "&").replace("&apos;", "'")
    return None

def discover_all(timeout_ms=3000, names=True):
    """Every Roku that answers SSDP: [{"kind", "name", "ip"}]."""
    search = b'M-SEARCH * HTTP/1.1\r\nHost: 239.255.255.250:1900\r\nMan: "ssdp:discover"\r\nST: roku:ecp\r\n\r\n'
    ips = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout_ms / 1000)
        address = socket.getaddrinfo("239.255.255.250", 1900)[0][-1]
        for _ in range(2): # UDP can drop one; SSDP clients usually ask twice
            sock.sendto(search, address)
        while True:
            for line in sock.recv(1024).decode().split("\r\n"):
                if line.lower().startswith("location:"): # LOCATION: http://192.168.1.20:8060/
                    ip = line.split("//", 1)[1].split(":")[0].split("/")[0]
                    if ip not in ips:
                        ips.append(ip)
    except OSError:
        pass
    finally:
        sock.close()
    return [{"kind": "roku", "name": (_name(ip) if names else None) or "Roku", "ip": ip} for ip in ips]

def discover(timeout_ms=3000):
    """The first Roku found, or None."""
    found = discover_all(timeout_ms, names=False)
    return found[0]["ip"] if found else None
