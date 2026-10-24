#Config
# Wi-Fi, Roku and Jellyfin settings are entered in setup mode and saved to settings.json on the board.

JELLYFIN_APP_ID = "592369" # Roku channel ID of the Jellyfin app
JELLYFIN_CLIENT = "Jellyfin Roku" # Session "Client" name of the TV app in Jellyfin

# PN532 I2C pins on the ESP32-S3
NFC_SDA_PIN = 8
NFC_SCL_PIN = 9

LEARN_TIMEOUT_S = 120 # How long a new card waits for a movie to start
LINK_TIMEOUT_S = 300 # How long to wait for a link from your phone (non-Jellyfin apps)

WEB_PORT = 80 # The ESP32's link page for pasting links (non-Jellyfin apps)
