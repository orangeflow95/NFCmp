#Config
# Wi-Fi, TV and media server settings are entered in setup mode and saved to settings.json on the board.

JELLYFIN_APP_ID = "592369" # Roku channel ID of the Jellyfin app
JELLYFIN_ANDROID_TV = "org.jellyfin.androidtv" # Package of the Jellyfin app on Google TV
PLEX_APP_ID = "13535" # Roku channel ID of the Plex app
# Session "Client" name of the Jellyfin TV app, and player "product" name of the Plex TV app, per kind of TV
JELLYFIN_CLIENT = {"roku": "Jellyfin Roku", "googletv": "Android TV"}
PLEX_PRODUCT = {"roku": "Plex for Roku", "googletv": "Plex for Android (TV)"}

# Card record "svc" -> how each kind of TV opens it, and the fields it needs (see card.py).
#   roku:     Roku app ID, deep linked with ?contentId=<id>&mediaType=<movie|series|episode>.
#             Every one was checked against the TV's query/apps.
#   googletv: app link opened through the Android TV remote protocol ({id} is the card's ID),
#             or one link per card type. Jellyfin is played through its server instead (tv.py).
# "Untested" means nobody has yet confirmed that app opens a title from a card.
SERVICES = {
    "netflix":  {"roku": "12", "googletv": "https://www.netflix.com/title/{id}", "needs": ["id", "type"]},          # Roku verified; Google TV untested
    "jellyfin": {"roku": JELLYFIN_APP_ID, "needs": ["id"]},                                                         # Roku verified; Google TV untested
    "plex":     {"roku": PLEX_APP_ID, "needs": ["id", "type"]},                                                     # Not installed on the Roku; no Google TV link yet
    "disney":   {"roku": "291097", "googletv": "https://www.disneyplus.com/browse/entity-{id}", "needs": ["id", "type"]}, # Roku: movie entity ID plays (slow start); shows and Google TV untested
    "hulu":     {"roku": "2285", "googletv": "https://www.hulu.com/watch/{id}", "needs": ["id", "type"]},              # Untested
    "prime":    {"roku": "13", "googletv": "https://www.primevideo.com/detail/{id}", "needs": ["id", "type"]},        # Untested
    "appletv":  {"roku": "551012", "googletv": {"movie": "https://tv.apple.com/movie/{id}", "show": "https://tv.apple.com/show/{id}"}, "needs": ["id", "type"]}, # Untested
    "max":      {"roku": "61322", "googletv": {"movie": "https://play.max.com/movie/{id}", "show": "https://play.max.com/show/{id}"}, "needs": ["id", "type"]},   # Untested
    "youtube":  {"roku": "837", "googletv": "https://www.youtube.com/watch?v={id}", "needs": ["id"]},                  # Untested
}

# PN532 I2C pins on the ESP32-S3
NFC_SDA_PIN = 8
NFC_SCL_PIN = 9

LEARN_TIMEOUT_S = 120 # How long a new card waits for a movie to start

WEB_PORT = 80 # The player's web page: settings and TV pairing, plus library search and card writing for the iPhone app
WRITE_TIMEOUT_S = 120 # How long a card write from the app waits for a tap
PAIR_TIMEOUT_S = 300 # How long Google TV pairing waits for the code
