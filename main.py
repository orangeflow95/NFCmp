# Runs on an ESP32-S3 with MicroPython and a PN532 NFC reader over I2C.
# Tap a linked card: the TV turns on and plays what's linked to it.
# Each card holds its own record (card.py). The iPhone app picks a title and the
# next card tapped gets it written. A blank card can also learn from the media
# server: tap it, then start something in Jellyfin on the TV.
# The first time it's powered on, it opens a setup Wi-Fi network (see onboarding.py).
import json
import time
import network
from machine import I2C, Pin
import card
import config
import onboarding
import servers
import web
from pn532 import PN532

try:
    import requests
except ImportError:
    import urequests as requests

CARDS_FILE = "cards.json"
MEDIA_TYPES = {"Movie": "movie", "Episode": "episode"} # Jellyfin item type -> Roku deep link mediaType
WIFI_TIMEOUT_MS = 20000
HOSTNAME = "nfc-player" # Reachable as http://nfc-player.local/

settings = onboarding.load_settings() # Wi-Fi, Roku and media server, entered in setup mode

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
    """Joins the saved Wi-Fi. Returns the WLAN, or None if it can't connect in time."""
    try:
        network.hostname(HOSTNAME) # Must be set before the interface comes up
    except (AttributeError, ValueError):
        pass
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print(f"Connecting to Wi-Fi {settings['wifi_ssid']}...")
        wlan.connect(settings["wifi_ssid"], settings.get("wifi_password", ""))
        deadline = time.ticks_add(time.ticks_ms(), WIFI_TIMEOUT_MS)
        while not wlan.isconnected():
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                print("Couldn't connect to Wi-Fi.")
                return None
            time.sleep_ms(500)
    print(f"Wi-Fi connected: {wlan.ifconfig()[0]}")
    return wlan

def find_roku():
    print("Looking for the Roku...")
    ip = onboarding.discover_roku()
    if ip:
        settings["roku_ip"] = ip
        onboarding.save_settings(settings)
        print(f"Found the Roku at {ip}.")
    else:
        print("No Roku found. Is it on the same Wi-Fi? Enter its IP in setup mode (http://<player ip>/setup).")

def roku_post(path):
    """Sends a Roku ECP POST command."""
    r = requests.post(f"http://{settings['roku_ip']}:8060/{path}", headers={"Content-Length": "0"}, timeout=5)
    r.close()

def wake_tv():
    roku_post("keypress/PowerOn")
    time.sleep(3) # Wait for TV to wake up

def play(entry):
    """Turns on the TV and deep links the card's app straight into its movie or show.

    The Jellyfin Roku client doesn't support remote control through the
    Jellyfin Sessions API, so playback is started with Roku ECP deep linking.
    """
    print(f"▶ Playing '{entry['title']}'")
    app_id = entry.get("app", config.JELLYFIN_APP_ID)
    media_type = entry.get("media_type") or MEDIA_TYPES.get(entry.get("type"), "movie")
    try:
        wake_tv()
        roku_post(f"launch/{app_id}?contentId={entry['id']}&mediaType={media_type}")
    except Exception as e:
        print(f"Roku Error: {e}")

SETUP_CONFIRM = f"""<h2>Change settings</h2><p>The player will restart and open its own Wi-Fi network,
<b>{onboarding.AP_NAME}</b>. Join it on your phone to change the Wi-Fi, Roku or media server settings.</p>
<form action=/setup><button class=t name=confirm value=1>Restart in setup mode</button></form>"""
SETUP_RESTARTING = f"<h2>Restarting…</h2><p>Join the <b>{onboarding.AP_NAME}</b> Wi-Fi network on your phone.</p>"

def library_results(text):
    """The /library JSON for the iPhone app: the media server's matches for text."""
    try:
        items = servers.search_library(settings, text) if text.strip() else []
    except Exception as e:
        return {"server": settings.get("media_server"), "items": [], "error": str(e)}
    return {"server": settings.get("media_server") if items is not None else None, "items": items or []}

class PlayerPage:
    """The player's tiny web server: a status page, /setup, and for the iPhone app
    /library (search the media server) and /write (write a record to the next card tapped).
    """

    def __init__(self, ip, port, problem=None):
        self.url = f"http://{ip}/" if port == 80 else f"http://{ip}:{port}/"
        self.sock = web.listen(port)
        self.problem = problem # Shown on the status page, e.g. a media server sign-in that failed
        self.pending = None # (record text, deadline) while waiting for a card to write
        self.write_state = {"state": "idle"} # What GET /write reports to the app

    def start_write(self, form):
        """POST /write: record=<text> waits for the next card tapped; cancel=1 stops waiting."""
        if form.get("cancel"):
            self.pending = None
            self.write_state = {"state": "idle"}
            return self.write_state
        text = form.get("record", "").strip()
        fields = card.parse(text)
        reason = card.problem(fields) if fields else "That isn't a card record."
        if reason:
            return {"state": "failed", "error": reason}
        self.pending = (text, time.ticks_add(time.ticks_ms(), config.WRITE_TIMEOUT_S * 1000))
        self.write_state = {"state": "waiting", "title": card.to_card(fields)["title"]}
        print(f"📝 Tap a card to write '{self.write_state['title']}' to it.")
        return self.write_state

    def poll(self):
        """Answers one waiting request, if any."""
        client = web.accept(self.sock)
        if not client:
            return
        restart = False
        try:
            method, path, _, form = web.read_request(client)
            if path == "/setup":
                restart = bool(form.get("confirm"))
                web.send(client, "Settings", SETUP_RESTARTING if restart else SETUP_CONFIRM)
            elif path == "/library":
                web.send_json(client, library_results(form.get("q", "")))
            elif path == "/write":
                web.send_json(client, self.start_write(form) if method == "POST" else self.write_state)
            else:
                problem = f"<p class=e>⚠️ {web.escape(self.problem)}</p>" if self.problem else ""
                web.send(client, "NFC Movie Player", f"""<h2>NFC Movie Player</h2>{problem}
<p>Pick titles for your cards in the iPhone app.</p><p><a href=/setup>Change settings</a></p>""")
        except OSError:
            pass
        finally:
            client.close()
        if restart:
            onboarding.request_setup()

    def expire_write(self):
        if self.pending and time.ticks_diff(self.pending[1], time.ticks_ms()) <= 0:
            self.pending = None
            self.write_state = {"state": "expired"}
            print("⌛ No card was tapped. Write cancelled.")

def wait_with_taps(taps, page, ms):
    """Waits, answering the web page. Returns True if a card was tapped (cancel)."""
    until = time.ticks_add(time.ticks_ms(), ms)
    while time.ticks_diff(until, time.ticks_ms()) > 0:
        if taps.poll():
            return True
        page.poll()
        time.sleep_ms(100)
    return False

def learn(uid, cards, taps, page):
    """Locks whatever starts playing on the media server's TV app to the card. Any tap cancels.

    Only the media server (Jellyfin) can say what's playing. Cards for streaming
    apps are linked from the iPhone app instead.
    """
    if not servers.roku_app(settings):
        print("Blank card. Link it to a title from the iPhone app.")
        return
    print(f"New card! Start something in the media server app on the TV within {config.LEARN_TIMEOUT_S}s to lock it to this card.")
    try:
        wake_tv()
    except Exception as e:
        print(f"Roku Error: {e}")

    # Ignore whatever is already playing, unless it gets stopped and started again
    try:
        before = servers.now_playing(settings)
    except Exception as e:
        print(f"Media Server Error: {e}")
        before = None
    before_id = before["id"] if before else None
    stopped = before is None

    deadline = time.ticks_add(time.ticks_ms(), config.LEARN_TIMEOUT_S * 1000)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        # Check every 3 seconds, watching for a cancel tap in between
        if wait_with_taps(taps, page, 3000):
            print("❌ Cancelled. Card not linked.")
            return
        try:
            found = servers.now_playing(settings)
        except Exception as e:
            print(f"Media Server Error: {e}")
            continue
        if not found:
            stopped = True
        elif stopped or found["id"] != before_id:
            cards[uid] = found
            save_cards(cards)
            print(f"🔒 Locked '{found['title']}' to card {uid}.")
            save_to_card(taps.reader, found)
            return

    print("⌛ Timed out waiting for something to play. Card not linked.")

def save_to_card(reader, entry):
    """Writes a cards.json entry onto the card if it's still on the reader."""
    record = card.record_from_card(entry)
    if not record:
        return
    try:
        card.write_text(reader, record)
        print("💾 Saved the title onto the card itself.")
    except Exception:
        print("Tap the card again to save the title onto the card itself.")

def write_pending(uid, reader, cards, page):
    """Writes the record the app sent to the card just tapped."""
    text = page.pending[0]
    try:
        card.write_text(reader, text)
    except Exception as e:
        print(f"❌ Couldn't write the card: {e}")
        page.write_state = dict(page.write_state, error=f"{e} Tap the card again.")
        return
    page.pending = None
    entry = card.to_card(card.parse(text))
    cards[uid] = entry
    save_cards(cards)
    page.write_state = {"state": "written", "title": entry["title"]}
    print(f"✅ Wrote '{entry['title']}' to card {uid}.")

def handle_tap(uid, reader, cards, taps, page):
    if page.pending:
        write_pending(uid, reader, cards, page)
        return
    try:
        text = card.read_text(reader)
    except Exception as e:
        print(f"Couldn't read the card's record: {e}")
        text = None
    fields = card.parse(text) if text else None
    if fields:
        reason = card.problem(fields)
        if reason:
            print(f"⚠️ {reason}")
            return
        entry = card.to_card(fields)
        if cards.get(uid) != entry: # Keep a list of cards for the app
            cards[uid] = entry
            save_cards(cards)
        play(entry)
    elif uid in cards:
        play(cards[uid])
        save_to_card(reader, cards[uid]) # A card from before cards held their own records
    else:
        learn(uid, cards, taps, page)

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
    if onboarding.setup_requested() or not settings.get("wifi_ssid"):
        onboarding.run_portal(settings)
    wlan = connect_wifi()
    if not wlan:
        onboarding.run_portal(settings, f"Couldn't join {settings['wifi_ssid']}. Check the name and password.")
    if not settings.get("roku_ip"):
        find_roku()
    ip, mask = wlan.ifconfig()[:2]
    problem = servers.set_up(settings, servers.broadcast_address(ip, mask))
    if problem:
        print(f"⚠️ {problem}")
    reader = PN532(I2C(0, sda=Pin(config.NFC_SDA_PIN), scl=Pin(config.NFC_SCL_PIN), freq=100000))
    print(f"NFC reader ready: {reader.firmware}")
    page = PlayerPage(ip, config.WEB_PORT, problem)
    taps = TapReader(reader)
    cards = load_cards()
    print(f"{len(cards)} card(s) linked. Waiting for a tap...")

    while True:
        if not wlan.isconnected():
            connect_wifi() # Keep retrying; the router may be restarting
        uid = taps.poll()
        if uid:
            print(f"\n[NFC] Card tapped: {uid}")
            handle_tap(uid, reader, cards, taps, page)
            print("Waiting for a tap...")
        page.poll()
        page.expire_write()
        time.sleep_ms(100)

main()
