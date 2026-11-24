# onboarding.py
# First-time setup. With no saved Wi-Fi, or if the saved Wi-Fi can't be
# joined, the player opens its own Wi-Fi network. Joining it on a phone pops up
# a page that asks only for the home Wi-Fi. Everything else (the TV, Google TV
# pairing, a media server) is set up afterwards in the NFCMP app (see api.py).
# Settings are saved to settings.json on the board's flash.
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
SERVERS = {"jellyfin": "Jellyfin", "plex": "Plex"}
SERVER_KEYS = ("media_server", "server_url", "server_user", "server_password", "server_token")
PORTAL_TIMEOUT_S = 300 # With saved settings, give up after this long without a visit and retry the Wi-Fi

def load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            settings = json.load(f)
    except (OSError, ValueError):
        return {}
    if "roku_ip" in settings: # Saved before the player supported other TVs
        settings.setdefault("tv", "roku")
        settings.setdefault("tv_ip", settings.pop("roku_ip"))
    return settings

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
    options = "".join(f'<option value="{web.escape(name)}">' for name in networks)
    keep = " (blank keeps the saved one)" if settings.get("wifi_password") else ""
    error = f"<p class=e>{web.escape(error)}</p>" if error else ""
    return f"""<h2>Connect your movie player</h2>{error}
<p>Pick your home Wi-Fi. Once the player is on it, the NFCMP app finds it and sets up the rest.</p>
<form method=post action=/save>
<input class=t name=wifi_ssid list=nets value="{web.escape(settings.get('wifi_ssid', ''))}" placeholder="Wi-Fi name" required autocapitalize=off autocorrect=off>
<datalist id=nets>{options}</datalist>
<input class=t type=password name=wifi_password placeholder="Wi-Fi password{keep}">
<p class=h>The player needs a 2.4 GHz network. Most home Wi-Fi has one.</p>
<button class=t>Connect</button></form>"""

def apply_form(settings, form):
    """Returns the settings updated from the submitted form, and a problem with them or None."""
    new = dict(settings)
    new["wifi_ssid"] = form.get("wifi_ssid", "").strip()
    if form.get("wifi_password"): # Blank keeps the saved password
        new["wifi_password"] = form["wifi_password"]
    if not new["wifi_ssid"]:
        return new, "Pick your Wi-Fi network."
    return new, None

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
                    new, problem = apply_form(settings, form)
                    if problem:
                        web.send(client, "Set up", form_page(new, networks, problem))
                    else:
                        settings = new
                        save_settings(settings)
                        saved = True
                        web.send(client, "Saved", f"""<h2>✅ Connecting…</h2><p>The player is joining
<b>{web.escape(settings['wifi_ssid'])}</b>.</p>
<p><b>Next:</b> switch your phone back to your home Wi-Fi and open the <b>NFCMP</b> app. It finds the player and walks you through choosing your TV.</p>
<p class=h>If the password was wrong, the <b>{AP_NAME}</b> network comes back in a minute so you can try again.</p>""")
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
