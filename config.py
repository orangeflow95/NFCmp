#Config
# Wi-Fi, Roku and Jellyfin settings are entered in setup mode and saved to settings.json on the board.

JELLYFIN_APP_ID = "592369" # Roku channel ID of the Jellyfin app
JELLYFIN_CLIENT = "Jellyfin Roku" # Session "Client" name of the TV app in Jellyfin
PLEX_APP_ID = "13535" # Roku channel ID of the Plex app
PLEX_PRODUCT = "Plex for Roku" # Player "product" name of the TV app in Plex

# Card record "svc" -> Roku app and the fields its deep link needs (see card.py).
# Every app ID was checked against the TV's query/apps; "deep link untested" means
# nobody has yet confirmed that app opens a title from a card's content ID.
SERVICES = {
    "netflix":  {"app": "12", "needs": ["id", "type"]},                 # Verified on the TV
    "jellyfin": {"app": JELLYFIN_APP_ID, "needs": ["id"]},              # Verified on the TV
    "plex":     {"app": PLEX_APP_ID, "needs": ["id", "type"]},          # Not installed on the TV
    "disney":   {"app": "291097", "needs": ["id", "type"]},             # Deep link untested
    "hulu":     {"app": "2285", "needs": ["id", "type"]},               # Deep link untested
    "prime":    {"app": "13", "needs": ["id", "type"]},                 # Deep link untested
    "appletv":  {"app": "551012", "needs": ["id", "type"]},             # Deep link untested
    "max":      {"app": "61322", "needs": ["id", "type"]},              # Deep link untested
    "youtube":  {"app": "837", "needs": ["id"]},                        # Deep link untested
}

# PN532 I2C pins on the ESP32-S3
NFC_SDA_PIN = 8
NFC_SCL_PIN = 9

LEARN_TIMEOUT_S = 120 # How long a new card waits for a movie to start

WEB_PORT = 80 # The player's web page: settings, plus library search and card writing for the iPhone app
WRITE_TIMEOUT_S = 120 # How long a card write from the app waits for a tap
