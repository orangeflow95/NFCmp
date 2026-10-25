# phone.py
# Bluetooth LE link to the iPhone app. The player advertises one service with
# two characteristics: the link page's URL (read) and the latest event (read +
# notify). The app stays connected in the background and turns events into
# notifications. Wi-Fi can't push to a backgrounded iPhone app, which is why
# this uses Bluetooth.
#
# Events are short text, "kind" or "kind|detail":
#   learn            a blank card was tapped; start something on the TV
#   link|<app name>  something is playing in an app that needs a pasted link
#   locked|<title>   the card was linked
#   idle             learn mode ended without linking (cancelled or timed out)
from micropython import const

try:
    import bluetooth
except ImportError: # Firmware without Bluetooth: the player runs without phone alerts
    bluetooth = None

# Must match PlayerLink.swift in the iPhone app
SERVICE_UUID = "512cfdb7-839a-4a3c-9e7d-a94a96583b77"
PAGE_UUID = "2b62b7db-9e60-4101-a213-9914aa996fb4"
EVENT_UUID = "9b4f083c-41e6-4022-81f7-ce5c85c6a004"

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_ADV_INTERVAL_US = const(250_000)
_MAX_PHONES = const(3)

def _adv_field(kind, value):
    return bytes((len(value) + 1, kind)) + value

class PhoneLink:
    def __init__(self, name, page_url):
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.config(gap_name=name)
        self.ble.irq(self._irq)
        service = bluetooth.UUID(SERVICE_UUID)
        ((self.page, self.event),) = self.ble.gatts_register_services((
            (service, (
                (bluetooth.UUID(PAGE_UUID), bluetooth.FLAG_READ),
                (bluetooth.UUID(EVENT_UUID), bluetooth.FLAG_READ | bluetooth.FLAG_NOTIFY),
            )),
        ))
        self.ble.gatts_set_buffer(self.page, 64)
        self.ble.gatts_set_buffer(self.event, 128)
        self.ble.gatts_write(self.page, page_url)
        self.ble.gatts_write(self.event, "idle")
        self.phones = set()
        # The service UUID goes in the advertisement (iOS needs it to find the
        # player in the background); the name goes in the scan response.
        self.adv = _adv_field(0x01, b"\x06") + _adv_field(0x07, bytes(service))
        self.resp = _adv_field(0x09, name.encode())
        self._advertise()
        print(f"Bluetooth ready: '{name}'")

    def _advertise(self):
        if len(self.phones) < _MAX_PHONES: # Keep advertising so more than one phone can connect
            self.ble.gap_advertise(_ADV_INTERVAL_US, adv_data=self.adv, resp_data=self.resp)

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self.phones.add(data[0])
            print("📱 Phone connected over Bluetooth.")
            self._advertise()
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self.phones.discard(data[0])
            self._advertise()

    def send(self, kind, detail=None):
        """Updates the event and notifies every connected phone."""
        text = kind if detail is None else f"{kind}|{detail}"
        self.ble.gatts_write(self.event, text.encode()[:128])
        for phone in list(self.phones):
            try:
                self.ble.gatts_notify(phone, self.event)
            except OSError:
                self.phones.discard(phone)

class NoPhone:
    """Stand-in when Bluetooth isn't available, so the player works without it."""

    def send(self, kind, detail=None):
        pass

def start(name, page_url):
    if bluetooth is None:
        print("No Bluetooth in this firmware. Phone alerts are off.")
        return NoPhone()
    try:
        return PhoneLink(name, page_url)
    except Exception as e:
        print(f"Bluetooth Error: {e}. Phone alerts are off.")
        return NoPhone()
