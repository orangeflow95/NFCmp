# Runs on an ESP32-S3 with MicroPython and a PN532 NFC reader over I2C.
# Tap a linked card: the TV turns on and plays what's linked to it.
# Tap a new card, then start something on the TV:
#   - Jellyfin: it gets locked to the card automatically.
#   - Any other app (Netflix, YouTube, ...): open the ESP32's page on your phone
#     and paste the link to what you're watching.
import json
import socket
import time
import network
from machine import I2C, Pin
import config
from pn532 import PN532

try:
    import requests
except ImportError:
    import urequests as requests

CARDS_FILE = "cards.json"
MEDIA_TYPES = {"Movie": "movie", "Episode": "episode"} # Jellyfin item type -> Roku deep link mediaType
NETFLIX_APP_ID = "12"
YOUTUBE_APP_ID = "837"

def load_cards():
    try:
        with open(CARDS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def save_cards(cards):
    with open(CARDS_FILE, "w") as f:
        json.dump(cards, f)

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to Wi-Fi...")
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        while not wlan.isconnected():
            time.sleep_ms(500)
    print(f"Wi-Fi connected: {wlan.ifconfig()[0]}")
    return wlan

def roku_post(path):
    """Sends a Roku ECP POST command."""
    r = requests.post(f"http://{config.ROKU_IP}:8060/{path}", headers={"Content-Length": "0"}, timeout=5)
    r.close()

def roku_query(what):
    r = requests.get(f"http://{config.ROKU_IP}:8060/query/{what}", timeout=5)
    try:
        return r.text
    finally:
        r.close()

def tv_state():
    """Returns (app_id, app_name, is_playing) for the TV. app_id is None on the home screen."""
    xml = roku_query("active-app")
    start = xml.find("<app")
    app_id, app_name = None, "Roku"
    if start >= 0:
        tag_end = xml.find(">", start)
        tag = xml[start:tag_end]
        i = tag.find('id="')
        if i >= 0:
            app_id = tag[i + 4:tag.find('"', i + 4)]
        app_name = xml[tag_end + 1:xml.find("</app>", tag_end)]
    playing = 'state="play"' in roku_query("media-player")
    return app_id, app_name, playing

def wake_tv():
    roku_post("keypress/PowerOn")
    time.sleep(3) # Wait for TV to wake up

def play(card):
    """Turns on the TV and deep links the card's app straight into its movie or show.

    The Jellyfin Roku client doesn't support remote control through the
    Jellyfin Sessions API, so playback is started with Roku ECP deep linking.
    """
    print(f"▶ Playing '{card['title']}'")
    app_id = card.get("app", config.JELLYFIN_APP_ID)
    media_type = card.get("media_type") or MEDIA_TYPES.get(card.get("type"), "movie")
    try:
        wake_tv()
        roku_post(f"launch/{app_id}?contentId={card['id']}&mediaType={media_type}")
    except Exception as e:
        print(f"Roku Error: {e}")

def now_playing():
    """Returns the item currently playing in the Jellyfin Roku app, or None."""
    r = requests.get(
        f"{config.JELLYFIN_IP}/Sessions?activeWithinSeconds=600",
        headers={"Authorization": f'MediaBrowser Token="{config.API_KEY}"'},
        timeout=5,
    )
    try:
        sessions = r.json()
    finally:
        r.close()
    for session in sessions:
        if session.get("Client") == config.JELLYFIN_CLIENT and session.get("NowPlayingItem"):
            return session["NowPlayingItem"]
    return None

def _segment_after(text, marker):
    i = text.find(marker)
    if i < 0:
        return None
    rest = text[i + len(marker):]
    for stop in "?&#/":
        rest = rest.split(stop)[0]
    return rest or None

def content_id_from_link(app_id, link):
    """Pulls the ID the app's Roku deep link expects out of a pasted share link."""
    link = link.strip()
    if "http" in link:
        link = link[link.find("http"):].split()[0] # Share text like "Watch Arcane on Netflix: https://..."
    if app_id == NETFLIX_APP_ID:
        if link.isdigit():
            return link
        for marker in ("/title/", "/watch/", "jbv="):
            title_id = _segment_after(link, marker)
            if title_id and title_id.isdigit():
                return title_id
        return None
    if app_id == YOUTUBE_APP_ID:
        for marker in ("v=", "youtu.be/", "/shorts/", "/live/"):
            video_id = _segment_after(link, marker)
            if video_id:
                return video_id
        return link if len(link) == 11 and "." not in link else None
    # Other apps (or a bare ID): use the last part of the URL path
    path = link.split("?")[0].split("#")[0].rstrip("/")
    return path.split("/")[-1] or None

def unquote(text):
    """Decodes a URL-encoded form value."""
    parts = text.replace("+", " ").split("%")
    out = bytearray(parts[0].encode())
    for part in parts[1:]:
        try:
            out.append(int(part[:2], 16))
            out.extend(part[2:].encode())
        except ValueError:
            out.extend(("%" + part).encode())
    return bytes(out).decode()

def parse_query(path):
    fields = {}
    if "?" in path:
        for pair in path.split("?", 1)[1].split("&"):
            key_value = pair.split("=", 1)
            if len(key_value) == 2:
                fields[unquote(key_value[0])] = unquote(key_value[1])
    return fields

PAGE_HEAD = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Link card</title><style>body{font-family:-apple-system,sans-serif;max-width:30em;margin:2em auto;padding:0 1em}
.t{font-size:1.1em;width:100%;padding:.6em;margin:.4em 0;box-sizing:border-box}label{display:inline-block;margin:.5em 1em .5em 0}</style>"""

class LinkPage:
    """Tiny web server on the ESP32 where the phone pastes the link for a new card."""

    def __init__(self, ip, port):
        self.url = f"http://{ip}/" if port == 80 else f"http://{ip}:{port}/"
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(socket.getaddrinfo("0.0.0.0", port)[0][-1])
        self.sock.listen(2)
        self.sock.setblocking(False)
        self.waiting = None # (app_id, app_name) while waiting for a link
        self.result = None

    def ask(self, app_id, app_name):
        self.waiting = (app_id, app_name)
        self.result = None

    def stop(self):
        self.waiting = None

    def poll(self):
        """Answers one waiting request, if any. Returns the new card once a link is submitted."""
        try:
            client, _ = self.sock.accept()
        except OSError:
            return None
        try:
            client.settimeout(3)
            request = client.recv(2048).decode()
            path = request.split(" ")[1] if request.count(" ") >= 2 else "/"
            client.sendall(b"HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n\r\n")
            client.sendall((PAGE_HEAD + self._handle(parse_query(path))).encode())
        except OSError:
            pass
        finally:
            client.close()
        if self.result:
            self.waiting = None
        return self.result

    def _handle(self, form):
        if self.result:
            return f"<h2>✅ Card locked to {self.result['title']}</h2>"
        if not self.waiting:
            return "<h2>No card is waiting</h2><p>Tap a new card, then start something on the TV.</p>"
        app_id, app_name = self.waiting
        error = ""
        if form.get("link"):
            content_id = content_id_from_link(app_id, form["link"])
            if content_id:
                kind = "series" if form.get("kind") == "series" else "movie"
                title = form.get("name", "").strip() or f"{app_name} {content_id}"
                self.result = {"app": app_id, "id": content_id, "title": title, "media_type": kind}
                return f"<h2>✅ Card locked to {title}</h2><p>Tap the card any time to play it.</p>"
            error = "<p style=color:#c00>Couldn't find a title in that link. Try the share link from the app.</p>"
        return f"""<h2>What are you watching on {app_name}?</h2>{error}
<form action="/"><input class=t name=link placeholder="Paste the share link" required autofocus>
<input class=t name=name placeholder="Name (optional), e.g. Arcane">
<label><input type=radio name=kind value=movie checked> Movie</label>
<label><input type=radio name=kind value=series> Show</label>
<button class=t>Lock to card</button></form>"""

def wait_with_taps(taps, page, ms):
    """Waits, answering the link page. Returns True if a card was tapped (cancel)."""
    until = time.ticks_add(time.ticks_ms(), ms)
    while time.ticks_diff(until, time.ticks_ms()) > 0:
        if taps.poll():
            return True
        page.poll()
        time.sleep_ms(100)
    return False

def ask_phone(uid, cards, taps, page, app_id, app_name):
    """Waits for a link to what's playing on the link page and locks it to the card."""
    print(f"Something is playing on {app_name}. Open {page.url} on your phone and paste the link.")
    page.ask(app_id, app_name)
    deadline = time.ticks_add(time.ticks_ms(), config.LINK_TIMEOUT_S * 1000)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if taps.poll():
            page.stop()
            print("❌ Cancelled. Card not linked.")
            return
        card = page.poll()
        if card:
            cards[uid] = card
            save_cards(cards)
            print(f"🔒 Locked '{card['title']}' ({app_name}) to card {uid}.")
            return
        time.sleep_ms(100)
    page.stop()
    print("⌛ Timed out waiting for a link. Card not linked.")

def learn(uid, cards, taps, page):
    """Waits for something to start on the TV and locks it to the card. Any tap cancels."""
    print(f"New card! Start something on the TV within {config.LEARN_TIMEOUT_S}s to lock it to this card.")
    try:
        wake_tv()
    except Exception as e:
        print(f"Roku Error: {e}")

    # Ignore whatever is already playing, unless it gets stopped and started again
    try:
        before = now_playing()
    except Exception as e:
        print(f"Jellyfin Error: {e}")
        before = None
    before_id = before["Id"] if before else None
    jellyfin_stopped = before is None
    try:
        app_id, _, playing = tv_state()
        before_app = app_id if playing else None
    except Exception as e:
        print(f"Roku Error: {e}")
        before_app = None
    tv_stopped = before_app is None

    deadline = time.ticks_add(time.ticks_ms(), config.LEARN_TIMEOUT_S * 1000)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        # Check the TV every 3 seconds, watching for a cancel tap in between
        if wait_with_taps(taps, page, 3000):
            print("❌ Cancelled. Card not linked.")
            return

        try:
            app_id, app_name, playing = tv_state()
            if app_id == config.JELLYFIN_APP_ID:
                item = now_playing()
                if not item:
                    jellyfin_stopped = True
                elif jellyfin_stopped or item["Id"] != before_id:
                    cards[uid] = {"id": item["Id"], "title": item.get("Name", "Unknown Movie"), "type": item.get("Type")}
                    save_cards(cards)
                    print(f"🔒 Locked '{cards[uid]['title']}' to card {uid}.")
                    return
            elif not playing:
                tv_stopped = True
            elif app_id and (tv_stopped or app_id != before_app):
                ask_phone(uid, cards, taps, page, app_id, app_name)
                return
        except Exception as e:
            print(f"TV Error: {e}")

    print("⌛ Timed out waiting for something to play. Card not linked.")

class TapReader:
    """Reports each tap once, even if the card stays on the reader."""

    def __init__(self, reader):
        self.reader = reader
        self.last_uid = None
        self.last_seen = 0

    def poll(self):
        uid = self.reader.read_uid()
        now = time.ticks_ms()
        if uid is None:
            if time.ticks_diff(now, self.last_seen) > 1000:
                self.last_uid = None # Card was removed
            return None
        self.last_seen = now
        if uid == self.last_uid:
            return None
        self.last_uid = uid
        return uid

def main():
    wlan = connect_wifi()
    reader = PN532(I2C(0, sda=Pin(config.NFC_SDA_PIN), scl=Pin(config.NFC_SCL_PIN), freq=100000))
    print(f"NFC reader ready: {reader.firmware}")
    page = LinkPage(wlan.ifconfig()[0], config.WEB_PORT)
    taps = TapReader(reader)
    cards = load_cards()
    print(f"{len(cards)} card(s) linked. Waiting for a tap...")

    while True:
        if not wlan.isconnected():
            connect_wifi()
        uid = taps.poll()
        if uid:
            print(f"\n[NFC] Card tapped: {uid}")
            if uid in cards:
                play(cards[uid])
            else:
                learn(uid, cards, taps, page)
            print("Waiting for a tap...")
        page.poll()
        time.sleep_ms(100)

main()
