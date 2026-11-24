# api.py
# The JSON API the NFCMP app uses to finish setting up the player once it's on
# the home Wi-Fi: choose the TV, pair a Google TV, test the TV, sign in to a
# media server, and go back to Wi-Fi setup. Requests are GETs or form-encoded
# POSTs on the player's web port (like /library and /write); replies are JSON.
# Like the setup page, there's no sign-in: anyone on the home Wi-Fi can use it.
import time
import config
import onboarding
import servers
import tv

VERSION = "0.2"
broadcast = None # The home network's broadcast address, for finding media servers; set by main.py
server_problem = None # Why the media server sign-in failed, if it did
_pairing = None # (googletv.Pairing, deadline) while a Google TV shows a code

def status(settings):
    """Everything the app's setup screens show."""
    kind = tv.kind(settings)
    ready = True
    if tv.needs_identity(settings):
        import googletv
        ready = googletv.has_identity()
    kinds = [{"id": k, "name": n, "available": True} for k, n in tv.KINDS.items()]
    kinds += [{"id": k, "name": n, "available": False} for k, n in tv.COMING_SOON.items()]
    server = settings.get("media_server")
    return {
        "version": VERSION,
        "tv": {
            "kind": kind,
            "name": settings.get("tv_name") or tv.name(settings) if kind else tv.name(settings),
            "ip": settings.get("tv_ip") or None,
            "paired": bool(settings.get("tv_paired")) if kind == "googletv" else None,
            "pairingReady": ready, # False while the Google TV certificate is still being made
            "pairing": _pairing is not None,
            "problem": tv.problem(settings),
        },
        "tvKinds": kinds,
        "server": {
            "kind": server if server in onboarding.SERVERS else None,
            "url": settings.get("server_url") or None,
            "user": settings.get("server_user") or None,
            "signedIn": servers.signed_in(settings),
            "problem": server_problem,
        },
    }

def _valid_ip(text):
    parts = text.split(".")
    return len(parts) == 4 and all(p.isdigit() and int(p) < 256 for p in parts)

def set_tv(settings, form):
    """kind=roku|googletv, ip=<address> (blank: find it), name=<the TV's own name, from /api/tvs>."""
    kind = form.get("kind", "")
    if kind not in tv.KINDS:
        return {"error": "That TV isn't supported yet."}
    ip = form.get("ip", "").strip()
    if ip and not _valid_ip(ip):
        return {"error": "That isn't an IP address. It looks like 192.168.1.20."}
    if not ip:
        ip = tv.discover({"tv": kind})
        if not ip:
            return {"error": f"Couldn't find a {tv.KINDS[kind]} on this Wi-Fi. Make sure it's on, or enter its IP address."}
    if kind != settings.get("tv") or ip != settings.get("tv_ip"):
        settings.pop("tv_paired", None) # A different TV: pair again
        cancel_pairing()
    settings["tv"] = kind
    settings["tv_ip"] = ip
    settings["tv_name"] = form.get("name", "").strip()[:60] or tv.KINDS[kind]
    onboarding.save_settings(settings)
    print(f"📺 TV set to {tv.KINDS[kind]} at {ip}.")
    return status(settings)

def start_pairing(settings):
    global _pairing
    if tv.kind(settings) != "googletv" or not settings.get("tv_ip"):
        return {"error": "Choose your Google TV first."}
    import googletv
    if not googletv.has_identity():
        return {"error": "The player is still getting ready for Google TV. The first time takes a minute or two.", "notReady": True}
    cancel_pairing()
    pairing = googletv.Pairing(settings["tv_ip"])
    try:
        pairing.start()
    except ValueError as e:
        return {"error": str(e)}
    except Exception:
        return {"error": f"Couldn't reach the TV at {settings['tv_ip']}. Make sure it's on and on the same Wi-Fi."}
    _pairing = (pairing, time.ticks_add(time.ticks_ms(), config.PAIR_TIMEOUT_S * 1000))
    return {"ok": True}

def finish_pairing(settings, code):
    global _pairing
    if not _pairing:
        return {"error": "The code ran out. Start pairing again."}
    try:
        _pairing[0].finish(code)
    except ValueError as e: # A typo: the TV still shows the code
        if not _pairing[0].is_open():
            _pairing = None
        return {"error": str(e)}
    except Exception:
        _pairing = None
        return {"error": "The TV stopped pairing. Start again."}
    _pairing = None
    settings["tv_paired"] = True
    onboarding.save_settings(settings)
    print("📺 Paired with the Google TV.")
    return {"ok": True}

def cancel_pairing():
    global _pairing
    if _pairing:
        _pairing[0].close()
        _pairing = None

def set_server(settings, form):
    """kind=jellyfin|plex|(blank for none), url (blank: find it), user, password (blank keeps the sign-in)."""
    global server_problem
    kind = form.get("kind", "")
    if kind not in onboarding.SERVERS:
        for key in onboarding.SERVER_KEYS:
            settings.pop(key, None)
        server_problem = None
        onboarding.save_settings(settings)
        return status(settings)
    url = form.get("url", "").strip().rstrip("/")
    if url and not url.startswith("http"):
        url = "http://" + url
    user = form.get("user", "").strip()
    password = form.get("password", "")
    if not user:
        return {"error": f"Enter your {onboarding.SERVERS[kind]} username."}
    changed = kind != settings.get("media_server") or user != settings.get("server_user") or (url and url != settings.get("server_url"))
    if password or changed:
        if not password:
            return {"error": f"Enter your {onboarding.SERVERS[kind]} password."}
        settings.pop("server_token", None) # Sign in again
        settings["server_password"] = password
    if kind != settings.get("media_server") or url:
        settings["server_url"] = url # Blank: find it on the network
    settings["media_server"] = kind
    settings["server_user"] = user
    onboarding.save_settings(settings)
    server_problem = servers.set_up(settings, broadcast)
    return status(settings)

def handle(settings, method, path, form):
    """Answers an /api/ request. Returns the reply (a dict for JSON)."""
    if path == "/api/status":
        return status(settings)
    if path == "/api/tvs": # Takes several seconds: it waits for TVs to answer
        return {"tvs": tv.discover_all()}
    if method != "POST":
        return {"error": "Unknown request."}
    try:
        if path == "/api/tv":
            return set_tv(settings, form)
        if path == "/api/tv/test":
            tv.wake(settings)
            return {"ok": True}
        if path == "/api/pair/start":
            return start_pairing(settings)
        if path == "/api/pair/finish":
            return finish_pairing(settings, form.get("code", ""))
        if path == "/api/pair/cancel":
            cancel_pairing()
            return {"ok": True}
        if path == "/api/server":
            return set_server(settings, form)
        if path == "/api/wifi": # main.py restarts into Wi-Fi setup after replying
            return {"ok": True}
    except Exception as e:
        return {"error": str(e)}
    return {"error": "Unknown request."}

def tick(settings):
    """Background work, called from the main loop: ends a pairing nobody finished, and
    makes the Google TV certificate a little at a time when it might be needed."""
    if _pairing and time.ticks_diff(_pairing[1], time.ticks_ms()) <= 0:
        cancel_pairing()
    if tv.needs_identity(settings):
        import googletv
        googletv.make_identity_step()
