<p align="center"><img src="docs/images/banner.svg" alt="NFC Movie Player: tap a card and the TV plays it" width="100%"></p>

# NFCMP: NFC Movie Player

Put a movie or show on an NFC card. Tap the card on the player and the Roku TV turns on and starts it: Netflix, Jellyfin, Disney+ and more. Titles are picked in the **NFCMP** iPhone app and stored on the card itself.

- **Tap to play.** Each card holds its own title, so it works on any player and survives a wiped board.
- **Search everything.** The app searches your own Jellyfin library and every streaming service (through TMDB), and shows where each title streams in the US.
- **No typing on the board.** The first time it's powered on, the player opens its own Wi-Fi network with a setup page for your Wi-Fi, TV and media server. It finds the Roku and the Jellyfin server by itself.

> [!NOTE]
> Netflix and Jellyfin are proven on a real TV. Disney+, Hulu, Prime Video, Apple TV and Max cards are written in the same format, but whether each app opens the right title hasn't been tested yet.

## Contents

1. [How it works](#how-it-works)
2. [Bill of materials](#bill-of-materials)
3. [Build the hardware](#build-the-hardware) (steps 1–3)
4. [Install the software on the board](#install-the-software-on-the-board) (steps 4–8)
5. [First-time setup](#first-time-setup) (steps 9–10)
6. [Install the iPhone app](#install-the-iphone-app) (steps 11–12)
7. [Make your first card](#make-your-first-card) (steps 13–15)
8. [Updating later](#updating-later)
9. [What's on a card](#whats-on-a-card)
10. [Troubleshooting](#troubleshooting)
11. [Project layout](#project-layout)
12. [Credits](#credits)

---

## How it works

<p align="center"><img src="docs/images/overview.svg" alt="The iPhone app talks to the player over Wi-Fi; the player writes and reads cards and sends play commands to the Roku TV; the Jellyfin server supplies library search" width="100%"></p>

1. In the **NFCMP** app, search for a title and tap **Write to card**. The app sends the title to the player over Wi-Fi.
2. Tap a card on the player. The player writes the title onto the card.
3. From then on, tapping that card turns on the TV and opens the title using Roku's deep links.

The player is an ESP32-S3 running MicroPython, with a PN532 NFC reader connected over I2C.

---

## Bill of materials

<p align="center"><img src="docs/images/parts.svg" alt="ESP32-S3 dev board, PN532 NFC module, NTAG215 cards, four jumper wires and a USB-C data cable" width="100%"></p>

| Part | Qty | Notes | Link |
| --- | :-: | --- | --- |
| Waveshare ESP32-S3 Wi-Fi dev board (ESP32-S3-WROOM-1, **N16R8**: 16 MB flash, 8 MB PSRAM) | 1 | The brains. Laid out like Espressif's ESP32-S3-DevKitC-1. | [Amazon](https://www.amazon.com/dp/B0DLWGVXCS) |
| AITRIP PN532 NFC RFID module V3 | 1 | The card reader. Set to I2C mode in step 1. | [Amazon](https://www.amazon.com/dp/B0GTNRDXYB) |
| NTAG215 NFC cards or stickers | as many as you like | Your movie cards. About 500 bytes each, plenty for one title. | any |
| Female-to-female jumper wires | 4 | Red, black and two other colors make the wiring easy to check. | any |
| USB-C cable | 1 | **Must carry data**, not just charging. | any |

**You also need**

| Thing | Why |
| --- | --- |
| A Roku TV or Roku player | Plays the titles. Netflix, Jellyfin and the other apps must already be installed and signed in on it. |
| 2.4 GHz Wi-Fi | The ESP32 can't join 5 GHz networks. If your router shows a separate "5G" network, use the other one. |
| A Mac with Python 3 | To flash and copy code to the board. |
| An iPhone and Xcode | To install the NFCMP app. A free Apple ID works (see step 11). |
| A Jellyfin server (optional) | For library search and the blank-card shortcut. |
| A TMDB API key (free) | For searching streaming services in the app. Get one at [themoviedb.org](https://www.themoviedb.org/settings/api). |

> [!TIP]
> The white S50 card that comes with the PN532 kit is MIFARE Classic, not NTAG215. It's fine for checking the reader works, but it can't hold a title. Use NTAG215 cards for movies.

---

## Build the hardware

### Step 1: Set the PN532 to I2C

<p align="center"><img src="docs/images/pn532-switches.svg" alt="PN532 mode switches: switch 1 ON, switch 2 OFF for I2C" width="90%"></p>

**You'll need:** the PN532 module, a toothpick or small screwdriver.

1. Find the two tiny switches beside the PN532 chip.
2. Push **switch 1 to ON** and **switch 2 to OFF**.
3. Check against the table printed on the board: I2C is `1 0`.

> [!WARNING]
> Only flip the switches with the board unpowered. The PN532 reads them when it starts.

> [!TIP]
> If the PN532's header pins came loose in the bag, solder them on before wiring.

### Step 2: Wire the PN532 to the ESP32

<p align="center"><img src="wiring/pn532-esp32-wiring.png" alt="Wiring: PN532 GND to ESP32 GND, VCC to 3V3, SDA to GPIO 8, SCL to GPIO 9" width="80%"></p>

**You'll need:** both boards, 4 jumper wires.

Hold the ESP32 with the **USB-C port at the bottom**. Then connect:

| Wire | PN532 pin | ESP32-S3 pin | Where on the ESP32 |
| --- | --- | --- | --- |
| Red | VCC | **3V3** | Left header, top pin |
| Black | GND | **GND** | Right header, top pin (the bottom-left GND works too) |
| Blue | SDA | **GPIO 8** | Left header, 12th pin from the top |
| Orange | SCL | **GPIO 9** | Left header, 15th pin from the top |

> [!CAUTION]
> Use **3V3**, not **5V**. At 5V the PN532 can pull the data lines above what the ESP32's pins can take. The 5V pin is second from the bottom on the left; skip it.

> [!TIP]
> The PN532's header is usually labelled `GND VCC SDA SCL`. Go by the labels printed on your board, not by position. GPIO 8 and 9 are this board's standard I2C pins.

### Step 3: Plug the board into your Mac

1. Connect the ESP32's USB-C port to your Mac.
2. A red **PWR** light comes on.
3. Check the Mac can see it:

   ```sh
   ls /dev/cu.usbmodem*
   ```

   You should see something like `/dev/cu.usbmodem101`. That's the board's port.

> [!TIP]
> No port listed? The cable is probably charge-only. Try another one.

---

## Install the software on the board

<p align="center"><img src="docs/images/deploy.svg" alt="MicroPython is flashed once; the seven .py files are copied from the Mac to the board over USB-C" width="100%"></p>

### Step 4: Install the tools on your Mac

```sh
python3 -m pip install mpremote esptool
```

- **esptool** flashes MicroPython onto the board (once).
- **mpremote** copies the code and shows the board's log.

### Step 5: Get the code

```sh
git clone https://github.com/orangeflow95/NFCmp.git
cd NFCmp
```

Everything below runs from this `NFCmp` folder.

### Step 6: Flash MicroPython (first time only)

> [!IMPORTANT]
> Pick the **SPIRAM_OCT** variant. The N16R8 board has octal PSRAM, and the standard build won't use its 8 MB.

1. Download the **Octal-SPIRAM** firmware from [micropython.org/download/ESP32_GENERIC_S3](https://micropython.org/download/ESP32_GENERIC_S3/). The file is named like `ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin`.
2. Erase the board:

   ```sh
   esptool --chip esp32s3 erase-flash
   ```

3. Write MicroPython, using the file you downloaded:

   ```sh
   esptool --chip esp32s3 --baud 460800 write-flash 0 ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin
   ```

4. Press **RST** on the board to restart it.

<p align="center"><img src="docs/images/esp32-download-mode.svg" alt="Download mode: hold BOOT, tap RST, let go of BOOT" width="85%"></p>

> [!TIP]
> - **"Failed to connect":** put the board in download mode by hand. Hold **BOOT**, tap **RST**, let go of **BOOT**, then run the command again.
> - **Fails halfway:** drop `--baud 460800` to flash at the slower default speed.
> - **More than one board plugged in:** add `--port /dev/cu.usbmodem101` (your port from step 3).
> - **Older esptool:** the commands are `esptool.py` and `erase_flash` / `write_flash`.

### Step 7: Copy the code to the board

```sh
mpremote cp config.py pn532.py card.py web.py onboarding.py servers.py main.py :
```

The `:` at the end means "the board". `main.py` runs automatically every time the board starts.

| File | What it does |
| --- | --- |
| `main.py` | Reads taps, plays cards, writes titles sent from the app, runs the player's web page |
| `card.py` | The title record stored on each card |
| `pn532.py` | Talks to the NFC reader; reads and writes card memory |
| `onboarding.py` | The setup network and setup page; finds the Roku |
| `servers.py` | Finds Jellyfin (or Plex), signs in, searches the library |
| `web.py` | Small web-server helpers |
| `config.py` | Fixed settings: pins, timeouts, streaming app IDs |

> [!NOTE]
> Your Wi-Fi password and server sign-in are **not** in these files. You enter them on the setup page in step 9, and the board keeps them in its own `settings.json`.

### Step 8: Restart and watch the log

```sh
mpremote reset && mpremote repl
```

On a brand-new board you'll see:

```text
Setup mode: join the Wi-Fi network 'NFC Movie Player' on your phone (or open http://192.168.4.1/).
```

Press **Ctrl-]** to leave the log. The board keeps running.

> [!TIP]
> `PN532 not found. Check the wiring and that the board's switches are set to I2C.` means the reader didn't answer. Recheck step 1 and step 2, unplug USB, and plug it back in.

---

## First-time setup

### Step 9: Join the player's network

1. On your iPhone, open **Settings → Wi-Fi** and join **NFC Movie Player**. It's an open network with no password.
2. A setup sheet pops up. If it doesn't, open Safari and go to `http://192.168.4.1`.
3. Fill in the form:

<table>
<tr>
<td width="50%"><img src="docs/images/setup-wifi.png" alt="Setup page: tapping Wi-Fi name suggests nearby networks"></td>
<td width="50%"><img src="docs/images/setup-server.png" alt="Setup page: Jellyfin chosen as the media server, with username and password"></td>
</tr>
<tr>
<td><b>Wi-Fi.</b> Tap the name box: nearby networks are suggested above the keyboard. Enter the password.</td>
<td><b>Roku and media server.</b> Leave the Roku and server addresses blank and they're found automatically. Choose <b>Jellyfin</b> and enter the account the TV's Jellyfin app uses.</td>
</tr>
</table>

| Field | What to enter |
| --- | --- |
| Wi-Fi name / password | Your home **2.4 GHz** network |
| Roku IP address | Leave blank (found automatically) |
| Personal media server | None, Jellyfin or Plex |
| Server address | Leave blank (found automatically) |
| Username / password | Jellyfin: the TV app's account. Plex: your plex.tv account |

### Step 10: Save and connect

Tap **Save and connect**. The player restarts and joins your Wi-Fi. Switch your phone back to your home network.

In the log (`mpremote repl`) you'll see it find everything:

```text
Wi-Fi connected: 192.168.1.50
Looking for the Roku...
Found the Roku at 192.168.1.237.
Looking for the Jellyfin server...
Found Jellyfin at http://192.168.1.138:8096.
Signing in to Jellyfin...
Signed in to Jellyfin.
NFC reader ready: PN532 v1.6
0 card(s) linked. Waiting for a tap...
```

- **After sign-in:** the player keeps a login key and deletes your password.
- **Wrong Wi-Fi password:** after 20 seconds the **NFC Movie Player** network comes back, with your entries filled in.
- **Changing settings later:** open `http://nfc-player.local/setup` and tap **Restart in setup mode**, or use **Player settings** in the app.

---

## Install the iPhone app

### Step 11: Put NFCMP on your iPhone

1. Open `ios/NFCPlayer.xcodeproj` in Xcode.
2. Click **NFCPlayer** → **Signing & Capabilities** → **Team**, and choose your Apple ID. Add it under **Add Account** if it isn't listed.
3. Plug in your iPhone and pick it at the top of the Xcode window.
4. Press **▶ Run**.
5. On the iPhone, the first time:
   1. Turn on **Settings → Privacy & Security → Developer Mode**. The phone restarts.
   2. If iOS asks, trust your developer profile in **Settings → General → VPN & Device Management**.

> [!IMPORTANT]
> With a free Apple ID, the app stops opening after **7 days**. Plug in and press Run again to reinstall it. Your settings are kept. The paid Apple Developer Program ($99/year) makes it last a year.

> [!NOTE]
> The Xcode project is generated from `ios/project.yml` with [XcodeGen](https://github.com/yonaskolb/XcodeGen). If you add files or change settings, run `cd ios && xcodegen`.

### Step 12: Add your TMDB key

Open **NFCMP**. Paste your TMDB API key into the box at the top. It's saved only on your phone.

The badge in the top-left corner shows whether the app can reach the player:

| Badge | Meaning |
| --- | --- |
| ● **Online** (green) | The player answered at `nfc-player.local` |
| ● **Offline** (orange) | Not found. Check the phone and player are on the same Wi-Fi, or set the address under **⋯ → Player address**. |

---

## Make your first card

### Step 13: Find the title

<table>
<tr>
<td width="33%"><img src="docs/images/app-home.png" alt="NFCMP home screen with the search box"></td>
<td width="33%"><img src="docs/images/app-results.png" alt="Search results: In your Jellyfin first, then everything else from TMDB"></td>
<td width="33%"><img src="docs/images/app-card-options.png" alt="Card options for Frozen: Your Jellyfin, Disney+, and Netflix marked Not in the US"></td>
</tr>
<tr>
<td><b>1.</b> Type a movie or show and press Search.</td>
<td><b>2.</b> Titles <b>in your Jellyfin</b> come first. A green check marks streaming results you also own.</td>
<td><b>3.</b> Pick a title to see every way to play it. Services that don't stream it in the US have no button.</td>
</tr>
</table>

### Step 14: Write it to a card

<table>
<tr>
<td width="50%"><img src="docs/images/app-write-waiting.png" alt="Tap a card on the player"></td>
<td width="50%"><img src="docs/images/app-write-done.png" alt="Card ready"></td>
</tr>
<tr>
<td><b>1.</b> Tap <b>Write to card</b>, then tap an NTAG215 card on the player and <b>hold it still for a second</b>.</td>
<td><b>2.</b> <b>Card ready.</b> The title is now stored on the card.</td>
</tr>
</table>

- **The write fails** (the card moved): the app says so, and you just tap again.
- **No card within 2 minutes:** the player stops waiting. Tap **Try again** in the app.
- **Safe to pull away:** a card pulled away mid-write reads as blank, never half old and half new.

### Step 15: Play it

Tap the card on the player. The TV turns on, waits 3 seconds, and opens the title.

> [!TIP]
> **Jellyfin shortcut, no phone needed:** tap a **blank** card on the player, then start something in Jellyfin on the TV within 2 minutes. The card learns it. Tap any card to cancel.

> [!NOTE]
> **Netflix asks "Who's watching?":** pick your profile, then tap the card again. Netflix forgets the title when it shows the profile screen.

---

## Updating later

When the code changes, there's no need to flash MicroPython or redo setup:

```sh
cd NFCmp
git pull
mpremote cp config.py pn532.py card.py web.py onboarding.py servers.py main.py : && mpremote reset
```

Your settings (`settings.json`) and cards are kept. Cards carry their own titles, so even deleting the board's card list doesn't unlink them.

| Handy command | What it does |
| --- | --- |
| `mpremote repl` | Watch the log (Ctrl-] to leave) |
| `mpremote cat :cards.json` | List the cards the player has seen |
| `mpremote cp settings.json :` | Copy saved settings to a new board and skip setup |
| `mpremote rm :settings.json` | Forget all settings and redo setup |

---

## What's on a card

<p align="center"><img src="docs/images/card-record.svg" alt="A card record: v1;svc=netflix;type=show;id=81591296;t=Nobody Wants This" width="100%"></p>

Each card holds one standard NDEF text record, so any NFC app on a phone can read it. Some examples:

```text
v1;svc=netflix;type=show;id=81591296;t=Nobody Wants This
v1;svc=jellyfin;type=movie;id=183be3c815b9c0e6d1b9882e99439d72;t=Frozen
v1;svc=disney;type=movie;id=1JffnkWmY6mD;t=Frozen
```

| `svc` | Roku app | Status |
| --- | --- | --- |
| `netflix` | Netflix (12) | ✅ Plays on the TV |
| `jellyfin` | Jellyfin (592369) | ✅ Plays on the TV (IDs only work with your server) |
| `disney`, `hulu`, `prime`, `appletv`, `max` | Disney+, Hulu, Prime Video, Apple TV, HBO Max | ⚠️ App IDs confirmed, deep links untested |
| `youtube` | YouTube (837) | ⚠️ Untested |
| `plex` | Plex (13535) | ⚠️ Untested |

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `PN532 not found` in the log | Switches not on I2C (step 1), or SDA/SCL swapped or loose (step 2). Unplug and replug after fixing. |
| The setup sheet doesn't appear | Open `http://192.168.4.1` in Safari while joined to **NFC Movie Player**. |
| **NFC Movie Player** keeps coming back | The player can't join your Wi-Fi: wrong password, or a 5 GHz network. |
| App says **Offline** | Phone and player must be on the same Wi-Fi. Try **⋯ → Player address** with the IP from the log. |
| "Couldn't reach the player to search your library" | Same as Offline. TMDB results still work. |
| Write to card keeps failing | Hold the card flat and still on the reader for a full second. Use NTAG215, not the S50 card. |
| A card does nothing | It may be blank and no media server is set up; write a title to it from the app. |
| Netflix opens on its home screen | It showed "Who's watching?" first. Pick a profile and tap the card again. |
| A mature Netflix title won't play | Netflix uses the last profile; a Kids profile blocks it. |
| The app won't open | The free 7-day signing ran out. Reinstall from Xcode (step 11). |
| No **Write to card** button | That service doesn't stream it in the US, or Wikidata has no ID for it. |

---

## Project layout

```text
NFCmp/
├── main.py            Tap handling, playback, Jellyfin learning, web page
├── card.py            Card record format (NDEF text record)
├── pn532.py           PN532 driver: card UID, NTAG page read/write
├── onboarding.py      Setup network, captive setup page, Roku discovery
├── servers.py         Jellyfin/Plex discovery, sign-in, library search
├── web.py             Tiny HTTP helpers
├── config.py          Pins, timeouts, streaming app IDs
├── wiring/            Wiring diagram (PNG and SVG)
├── docs/images/       Pictures for this README
└── ios/               NFCMP iPhone app (SwiftUI, XcodeGen)
    ├── project.yml
    ├── NFCPlayer/
    └── NFCPlayerUITests/   Takes this README's app screenshots
```

---

## Credits

- This product uses the TMDB API but is not endorsed or certified by TMDB. Movie and show data from [TMDB](https://www.themoviedb.org).
- Where-to-watch data from [JustWatch](https://www.justwatch.com), through TMDB.
- Streaming IDs from [Wikidata](https://www.wikidata.org).
- ESP32-S3 pin positions from [CircuitState's pinout](https://www.circuitstate.com/pinouts/waveshare-esp32-s3-dev-kit-nxr8-wi-fi-development-board-pinout-diagram-arduino-reference/).
- Runs on [MicroPython](https://micropython.org).
