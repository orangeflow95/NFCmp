# servers.py
# Personal media servers (Jellyfin or Plex): finding them on the network,
# signing in, reading what the TV is playing for learn mode, and starting
# Jellyfin playback on Google TV.
# The Plex parts follow Plex's public APIs but haven't been tested on a real server.
import binascii
import json
import socket
import machine
import config
import onboarding
import tv
import web

try:
    import requests
except ImportError:
    import urequests as requests

DEVICE_ID = binascii.hexlify(machine.unique_id()).decode()
PRODUCT = "NFC Movie Player"

def signed_in(settings):
    """True if a media server is set up and signed in."""
    return bool(settings.get("media_server") in onboarding.SERVERS and settings.get("server_url") and settings.get("server_token"))

def _jellyfin(settings, path, method="GET"):
    r = requests.request(
        method, f"{settings['server_url']}{path}",
        headers={"Authorization": f'MediaBrowser Token="{settings["server_token"]}"', "Content-Length": "0"},
        timeout=5,
    )
    try:
        if r.status_code >= 400:
            raise ValueError(f"Jellyfin answered {r.status_code}")
        return r.json() if r.status_code == 200 and method == "GET" else None
    finally:
        r.close()

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

def search_library(settings, text):
    """Movies and shows on the media server matching text, for the iPhone app's search.

    Each has the server's item ID and, when the server knows it, the TMDB ID, so
    the app can match it to TMDB results. Returns None if the server isn't
    signed in or isn't supported yet (Plex).
    """
    if settings.get("media_server") != "jellyfin" or not signed_in(settings):
        return None
    url = settings["server_url"]
    items = _jellyfin(settings, f"/Items?searchTerm={web.quote(text)}&IncludeItemTypes=Movie,Series&Recursive=true&Fields=ProviderIds&Limit=20")["Items"]
    return [{
        "id": item["Id"],
        "title": item.get("Name", "Untitled"),
        "year": item.get("ProductionYear"),
        "kind": "tv" if item.get("Type") == "Series" else "movie",
        "tmdb": (item.get("ProviderIds") or {}).get("Tmdb"),
        "poster": f"{url}/Items/{item['Id']}/Images/Primary?maxHeight=300",
    } for item in items]

def _on_tv(session, settings):
    """True if a Jellyfin session is the TV's Jellyfin app."""
    return session.get("RemoteEndPoint") == settings.get("tv_ip") or session.get("Client") == config.JELLYFIN_CLIENT.get(tv.kind(settings))

def now_playing(settings):
    """Returns a card for what the TV is playing from the media server, or None."""
    if settings.get("media_server") == "plex":
        return _plex_now_playing(settings)
    for session in _jellyfin(settings, "/Sessions?activeWithinSeconds=600"):
        item = session.get("NowPlayingItem")
        if item and _on_tv(session, settings):
            return {"id": item["Id"], "title": item.get("Name", "Unknown Movie"), "type": item.get("Type")}
    return None

def remote_session(settings):
    """The ID of the TV's Jellyfin session if it takes remote control (Google TV), or None."""
    for session in _jellyfin(settings, "/Sessions?activeWithinSeconds=60"):
        if session.get("SupportsRemoteControl") and _on_tv(session, settings):
            return session["Id"]
    return None

def play_on_session(settings, session_id, item_id):
    _jellyfin(settings, f"/Sessions/{session_id}/Playing?playCommand=PlayNow&itemIds={item_id}", "POST")

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
        if config.PLEX_PRODUCT.get(tv.kind(settings), "Plex") in item.get("Player", {}).get("product", "") and item.get("type") in ("movie", "episode"):
            title = item.get("title", "Unknown Movie")
            if item.get("grandparentTitle"):
                title = f"{item['grandparentTitle']}: {title}"
            return {"app": config.PLEX_APP_ID, "id": item["ratingKey"], "title": title, "media_type": item["type"]}
    return None
