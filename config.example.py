#Config
# Copy this file to config.py and fill in your values. config.py is git-ignored.

WIFI_SSID = "your-wifi-name"
WIFI_PASSWORD = "your-wifi-password"

ROKU_IP = "192.168.1.x"
JELLYFIN_IP = "http://192.168.1.x:8096" # Include scheme and port
API_KEY = "your-jellyfin-api-key"
JELLYFIN_APP_ID = "592369"
JELLYFIN_CLIENT = "Roku" # Session Client name of the Roku app in Jellyfin

# PN532 I2C pins on the ESP32-S3
NFC_SDA_PIN = 8
NFC_SCL_PIN = 9

LEARN_TIMEOUT_S = 120 # How long a new card waits for a movie to start
LINK_TIMEOUT_S = 300 # How long to wait for a link from your phone (non-Jellyfin apps)

WEB_PORT = 80 # The ESP32's link page for pasting links (non-Jellyfin apps)
