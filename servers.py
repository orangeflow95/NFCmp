# servers.py
# Personal media servers (Jellyfin or Plex): finding them on the network,
# signing in, and reading what the Roku is playing for learn mode.
# The Plex parts follow Plex's public APIs but haven't been tested on a real server.
import binascii
import json
import socket
import machine
import config
import onboarding
import web

try:
    import requests
except ImportError:
    import urequests as requests

ROKU_APPS = {"jellyfin": config.JELLYFIN_APP_ID, "plex": config.PLEX_APP_ID}
DEVICE_ID = binascii.hexlify(machine.unique_id()).decode()
PRODUCT = "NFC Movie Player"

def roku_app(settings):
    """The Roku app ID of the signed-in media server, or None."""
    if settings.get("server_url") and settings.get("server_token"):
        return ROKU_APPS.get(settings.get("media_server"))
    return None

def broadcast_address(ip, mask):
    return ".".join(str(int(a) | (255 ^ int(m))) for a, m in zip(ip.split("."), mask.split(".")))

def _ask_network(message, port, broadcast, timeout_ms=3000):
    """Broadcasts a discovery message. Returns (reply, sender IP) of the first answer, or (None, None)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_BROADCAST", 0x20), 1)
        sock.settimeout(timeout_ms / 1000)
        sock.sendto(message, socket.getaddrinfo(broadcast, port)[0][-1])
        data, addr = sock.recvfrom(1024)
        return data.decode(), addr[0]
    except OSError:
        return None, None
    finally:
        sock.close()

def discover(kind, broadcast):
    """Finds a Jellyfin or Plex server on the network. Returns its base URL, or None."""
    if kind == "jellyfin":
        reply, _ = _ask_network(b"Who is JellyfinServer?", 7359, broadcast)
        try:
            return json.loads(reply)["Address"].rstrip("/") if reply else None
        except (ValueError, KeyError):
            return None
    reply, ip = _ask_network(b"M-SEARCH * HTTP/1.1\r\n\r\n", 32414, broadcast) # Plex "GDM"
    if not reply:
        return None
    port = "32400"
    for line in reply.split("\r\n"):
        if line.lower().startswith("port:"):
            port = line.split(":", 1)[1].strip()
    return f"http://{ip}:{port}"

def _jellyfin_login(settings):
    r = requests.post(
        f"{settings['server_url']}/Users/AuthenticateByName",
        headers={
            "Authorization": f'MediaBrowser Client="{PRODUCT}", Device="ESP32", DeviceId="{DEVICE_ID}", Version="1.0"',
            "Content-Type": "application/json",
        },
        data=json.dumps({"Username": settings.get("server_user", ""), "Pw": settings["server_password"]}),
        timeout=10,
    )
    try:
        if r.status_code == 401:
            raise ValueError("wrong username or password")
        if r.status_code != 200:
            raise ValueError(f"the server answered {r.status_code}")
        return r.json()["AccessToken"]
    finally:
        r.close()

def _plex_login(settings):
    r = requests.post(
        "https://plex.tv/api/v2/users/signin",
        headers={
            "X-Plex-Client-Identifier": DEVICE_ID,
            "X-Plex-Product": PRODUCT,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=f"login={web.quote(settings.get('server_user', ''))}&password={web.quote(settings['server_password'])}&rememberMe=true",
        timeout=10,
    )
    try:
        if r.status_code == 401:
            raise ValueError("wrong email/username or password")
        if r.status_code not in (200, 201):
            raise ValueError(f"plex.tv answered {r.status_code}")
        return r.json()["authToken"]
    finally:
        r.close()

def set_up(settings, broadcast):
    """Finds the media server and signs in, if that hasn't happened yet.

    Setup mode can't do this because the board isn't on the home Wi-Fi then.
    Returns a problem to show on the link page, or None.
    """
    kind = settings.get("media_server")
    if kind not in onboarding.SERVERS:
        return None
    name = onboarding.SERVERS[kind]
    if not settings.get("server_url"):
        print(f"Looking for the {name} server...")
        url = discover(kind, broadcast)
        if not url:
            return f"Couldn't find a {name} server on the Wi-Fi. Enter its address in settings."
        settings["server_url"] = url
        onboarding.save_settings(settings)
        print(f"Found {name} at {url}.")
    if not settings.get("server_token"):
        if "server_password" not in settings:
            return f"Enter your {name} sign-in in settings."
        print(f"Signing in to {name}...")
        try:
            token = (_jellyfin_login if kind == "jellyfin" else _plex_login)(settings)
        except ValueError as e:
            return f"Couldn't sign in to {name}: {e}."
        except Exception as e:
            return f"Couldn't reach {name} to sign in ({e}). It will try again on the next restart."
        settings["server_token"] = token
        del settings["server_password"] # Only the token is kept
        onboarding.save_settings(settings)
        print(f"Signed in to {name}.")
    return None

def now_playing(settings):
    """Returns a card for what the Roku is playing from the media server, or None."""
    if settings.get("media_server") == "plex":
        return _plex_now_playing(settings)
    r = requests.get(
        f"{settings['server_url']}/Sessions?activeWithinSeconds=600",
        headers={"Authorization": f'MediaBrowser Token="{settings["server_token"]}"'},
        timeout=5,
    )
    try:
        sessions = r.json()
    finally:
        r.close()
    for session in sessions:
        item = session.get("NowPlayingItem")
        if session.get("Client") == config.JELLYFIN_CLIENT and item:
            return {"id": item["Id"], "title": item.get("Name", "Unknown Movie"), "type": item.get("Type")}
    return None

def _plex_now_playing(settings):
    r = requests.get(
        f"{settings['server_url']}/status/sessions",
        headers={"X-Plex-Token": settings["server_token"], "Accept": "application/json"},
        timeout=5,
    )
    try:
        sessions = r.json()["MediaContainer"].get("Metadata", [])
    finally:
        r.close()
    for item in sessions:
        if config.PLEX_PRODUCT in item.get("Player", {}).get("product", "") and item.get("type") in ("movie", "episode"):
            title = item.get("title", "Unknown Movie")
            if item.get("grandparentTitle"):
                title = f"{item['grandparentTitle']}: {title}"
            return {"app": config.PLEX_APP_ID, "id": item["ratingKey"], "title": title, "media_type": item["type"]}
    return None
