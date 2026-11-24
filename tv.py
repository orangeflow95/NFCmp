# tv.py
# The TV the player drives, picked in the NFCMP app: finding it, turning it on, and
# opening a card's title in the right app. Cards don't name a TV, only the
# service and its ID (card.py), so the same card plays on any kind of TV.
# Each TV's module is imported only when that TV is picked, so a Roku player
# never loads the Google TV code (googletv.py, tlskey.py) into memory.
import time
import card
import config

KINDS = {"roku": "Roku", "googletv": "Google TV"}
COMING_SOON = {"samsung": "Samsung"} # Listed in the app, not selectable yet

def kind(settings):
    """"roku", "googletv", or None until a TV is chosen in the app."""
    return settings.get("tv") if settings.get("tv") in KINDS else None

def name(settings):
    return KINDS.get(kind(settings), "TV")

def discover(settings):
    """Finds the chosen kind of TV on the network. Returns its IP, or None."""
    return _module(settings).discover() if kind(settings) else None

def discover_all():
    """Every Roku and Google TV on the network, for the app's TV list."""
    import googletv
    import roku
    return roku.discover_all() + googletv.discover_all()

def _module(settings):
    if kind(settings) == "googletv":
        import googletv
        return googletv
    import roku
    return roku

def needs_identity(settings):
    """Whether to make the Google TV certificate in the background: for a Google TV,
    or before any TV is chosen, so it's ready if the user picks one."""
    return kind(settings) in ("googletv", None)

def problem(settings):
    """What stops cards playing on the TV, for the app and the status page, or None."""
    if not kind(settings):
        return "Choose your TV in the NFCMP app."
    if not settings.get("tv_ip"):
        return f"No {name(settings)} found. Is it on the same Wi-Fi? Enter its IP address in settings."
    if kind(settings) == "googletv" and not settings.get("tv_paired"):
        return "The player isn't paired with the Google TV yet."
    return None

def wake(settings):
    _module(settings).wake(settings["tv_ip"])

def googletv_link(fields):
    """The app link that opens a card's title on Google TV."""
    link = config.SERVICES[fields["svc"]].get("googletv")
    if isinstance(link, dict): # Different links for movies and shows
        link = link.get(fields.get("type")) or link.get("movie")
    if not link:
        raise ValueError(f"{fields['svc']} cards can't play on Google TV yet.")
    return link.replace("{id}", fields["id"])

def play(settings, fields):
    """Turns the TV on and opens the card's title. fields come from card.parse()."""
    if problem(settings) and not (kind(settings) and settings.get("tv_ip")):
        raise ValueError(problem(settings))
    ip = settings["tv_ip"]
    if kind(settings) == "roku":
        import roku
        roku.play(ip, config.SERVICES[fields["svc"]]["roku"], fields["id"], card.MEDIA_TYPES.get(fields.get("type"), "movie"))
    elif fields["svc"] == "jellyfin":
        _jellyfin_on_googletv(settings, fields["id"])
    else:
        import googletv
        googletv.open_link(ip, googletv_link(fields))

def _jellyfin_on_googletv(settings, item_id):
    """Opens the Jellyfin app, then starts the item through the Jellyfin server.

    The Jellyfin Android TV app has no deep links to items, but unlike the Roku
    app it accepts remote control from the server (POST /Sessions/{id}/Playing).
    """
    import googletv
    import servers # Here, not at the top: servers imports this module
    if settings.get("media_server") != "jellyfin" or not servers.signed_in(settings):
        raise ValueError("Jellyfin cards on Google TV need Jellyfin signed in: Player settings → Media server in the app.")
    ip = settings["tv_ip"]
    googletv.open_link(ip, "market://launch?id=" + config.JELLYFIN_ANDROID_TV)
    deadline = time.ticks_add(time.ticks_ms(), 20000)
    while True:
        session = servers.remote_session(settings)
        if session:
            servers.play_on_session(settings, session, item_id)
            return
        if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
            raise ValueError("The Jellyfin app on the TV didn't show up on the server. Is it signed in?")
        time.sleep_ms(1000)
