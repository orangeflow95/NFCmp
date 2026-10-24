# onboarding.py
# First-time setup. With no saved settings, or if the saved Wi-Fi can't be
# joined, the player opens its own Wi-Fi network. Joining it on a phone pops up
# a setup page for the home Wi-Fi, the Roku and Jellyfin. Settings are saved to
# settings.json on the board's flash.
import json
import os
import socket
import time
import machine
import network
import web

SETTINGS_FILE = "settings.json"
SETUP_FLAG_FILE = "setup.flag" # Written by the link page's "Change settings" button
AP_NAME = "NFC Movie Player"
FIELDS = ("wifi_ssid", "wifi_password", "roku_ip", "jellyfin_url", "jellyfin_key")
SECRET_FIELDS = ("wifi_password", "jellyfin_key") # Left blank on the form = keep the saved value
PORTAL_TIMEOUT_S = 300 # With saved settings, give up after this long without a visit and retry the Wi-Fi

def load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

def request_setup():
    """Restarts the player into setup mode."""
    with open(SETUP_FLAG_FILE, "w") as f:
        f.write("1")
    machine.reset()

def setup_requested():
    """True once after request_setup()."""
    try:
        os.remove(SETUP_FLAG_FILE)
        return True
    except OSError:
        return False

def discover_roku(timeout_ms=3000):
    """Finds a Roku on the network with SSDP. Returns its IP, or None."""
    search = b'M-SEARCH * HTTP/1.1\r\nHost: 239.255.255.250:1900\r\nMan: "ssdp:discover"\r\nST: roku:ecp\r\n\r\n'
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout_ms / 1000)
        sock.sendto(search, socket.getaddrinfo("239.255.255.250", 1900)[0][-1])
        while True:
            for line in sock.recv(1024).decode().split("\r\n"):
                if line.lower().startswith("location:"): # LOCATION: http://192.168.1.20:8060/
                    return line.split("//", 1)[1].split(":")[0].split("/")[0]
    except OSError:
        return None
    finally:
        sock.close()

def scan_networks(sta):
    """Returns nearby Wi-Fi names, strongest first."""
    try:
        found = sorted(sta.scan(), key=lambda n: -n[3])
    except OSError:
        return []
    names = []
    for n in found:
        try:
            name = n[0].decode()
        except UnicodeError:
            continue
        if name and name not in names:
            names.append(name)
    return names

class CaptiveDNS:
    """Answers every DNS lookup with the player's own IP, so phones open the setup page."""

    def __init__(self, ip):
        self.ip = bytes([int(part) for part in ip.split(".")])
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(socket.getaddrinfo("0.0.0.0", 53)[0][-1])
        self.sock.setblocking(False)

    def poll(self):
        try:
            query, addr = self.sock.recvfrom(512)
        except OSError:
            return
        end = 12 # Skip the header, then walk the question's name labels
        while end < len(query) and query[end]:
            end += query[end] + 1
        if end + 5 > len(query):
            return
        question = query[12:end + 5] # Name, its zero byte, type and class
        is_a = query[end + 1:end + 3] == b"\x00\x01"
        answer = b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + self.ip if is_a else b""
        reply = query[:2] + b"\x81\x80\x00\x01" + (b"\x00\x01" if is_a else b"\x00\x00") + b"\x00\x00\x00\x00" + question + answer
        try:
            self.sock.sendto(reply, addr)
        except OSError:
            pass

def form_page(settings, networks, error):
    value = lambda key: web.escape(settings.get(key, ""))
    keep = " (blank keeps the saved one)"
    options = "".join(f'<option value="{web.escape(name)}">' for name in networks)
    error = f"<p style=color:#c00>{web.escape(error)}</p>" if error else ""
    return f"""<h2>Set up your movie player</h2>{error}
<form method=post action=/save>
<h3>Wi-Fi</h3>
<input class=t name=wifi_ssid list=nets value="{value('wifi_ssid')}" placeholder="Wi-Fi name" required autocapitalize=off autocorrect=off>
<datalist id=nets>{options}</datalist>
<input class=t type=password name=wifi_password placeholder="Wi-Fi password{keep if settings.get('wifi_password') else ''}">
<h3>Roku</h3>
<input class=t name=roku_ip value="{value('roku_ip')}" placeholder="Roku IP address" inputmode=decimal>
<p class=h>Leave blank to find it automatically. On the Roku: Settings → Network → About.</p>
<h3>Jellyfin (optional)</h3>
<input class=t name=jellyfin_url value="{value('jellyfin_url')}" placeholder="Server, e.g. http://192.168.1.5:8096" autocapitalize=off autocorrect=off>
<input class=t type=password name=jellyfin_key placeholder="API key{keep if settings.get('jellyfin_key') else ''}">
<p class=h>In Jellyfin: Dashboard → API Keys. Without Jellyfin, new cards are linked by pasting a share link.</p>
<button class=t>Save and connect</button></form>"""

def apply_form(settings, form):
    """Returns the settings updated from the submitted form."""
    new = dict(settings)
    for key in FIELDS:
        value = form.get(key, "")
        if key not in SECRET_FIELDS:
            new[key] = value.strip()
        elif value:
            new[key] = value
    url = new["jellyfin_url"].rstrip("/")
    if url and not url.startswith("http"):
        url = "http://" + url
    new["jellyfin_url"] = url
    return new

def run_portal(settings, error=None):
    """Runs the setup network until settings are saved, then restarts. Never returns."""
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    sta.disconnect() # Stop retrying the old network so the scan works
    networks = scan_networks(sta)
    sta.active(False)

    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=AP_NAME, authmode=network.AUTH_OPEN)
    while not ap.active():
        time.sleep_ms(100)
    ip = ap.ifconfig()[0]
    dns = CaptiveDNS(ip)
    server = web.listen(80)
    print(f"Setup mode: join the Wi-Fi network '{AP_NAME}' on your phone (or open http://{ip}/).")

    deadline = time.ticks_add(time.ticks_ms(), PORTAL_TIMEOUT_S * 1000)
    while not settings.get("wifi_ssid") or time.ticks_diff(deadline, time.ticks_ms()) > 0:
        dns.poll()
        client = web.accept(server)
        if client:
            deadline = time.ticks_add(time.ticks_ms(), PORTAL_TIMEOUT_S * 1000)
            saved = False
            try:
                method, path, headers, form = web.read_request(client)
                if headers.get("host", ip).split(":")[0] != ip:
                    # A phone checking for internet: send it to the setup page
                    web.send(client, status="302 Found", headers=f"Location: http://{ip}/\r\n")
                elif method == "POST" and path == "/save":
                    settings = apply_form(settings, form)
                    save_settings(settings)
                    saved = True
                    web.send(client, "Saved", f"""<h2>✅ Saved</h2><p>The player is restarting and joining
<b>{web.escape(settings['wifi_ssid'])}</b>. You can switch your phone back to your home Wi-Fi.</p>
<p>If it can't connect, the <b>{AP_NAME}</b> network comes back so you can fix the settings.</p>""")
                else:
                    web.send(client, "Set up", form_page(settings, networks, error))
            except OSError:
                pass
            finally:
                client.close()
            if saved:
                print("Settings saved. Restarting...")
                time.sleep(2)
                machine.reset()
        time.sleep_ms(20)
    print("No changes made in setup mode. Restarting to try the Wi-Fi again.")
    machine.reset()
