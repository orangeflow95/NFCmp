# card.py
# What a card holds: one NDEF text record with versioned key=value pairs, e.g.
#   v1;svc=netflix;type=show;id=81591296;t=Nobody Wants This
# svc picks the app (config.SERVICES); t (title) is optional. Nothing on the card
# names a TV, so the same card plays on a Roku or a Google TV.
# Cards are NTAG215 stickers: 4-byte pages, user memory from page 4.
import config

FIRST_PAGE = 4
MAX_BYTES = 512 # NTAG215 has 504 bytes of user memory
CC_NTAG215 = b"\xe1\x10\x3e\x00" # Capability container of a blank, NDEF-formatted NTAG215
MEDIA_TYPES = {"movie": "movie", "show": "series", "episode": "episode"} # Card type -> Roku deep link mediaType

def parse(text):
    """Returns the record's fields as a dict, or None if it isn't a v1 card record."""
    parts = text.split(";")
    if parts[0] != "v1":
        return None
    fields = {}
    for part in parts[1:]:
        key, _, value = part.partition("=")
        if key:
            fields[key] = value
    return fields if fields.get("svc") and fields.get("id") else None

def problem(fields):
    """Why the player can't play these fields, or None."""
    service = config.SERVICES.get(fields["svc"])
    if not service:
        return f"Unknown service '{fields['svc']}'."
    missing = [key for key in service["needs"] if not fields.get(key)]
    return f"The {fields['svc']} record is missing {', '.join(missing)}." if missing else None

def to_card(fields):
    """The cards.json entry for a record's fields."""
    return {
        "app": config.SERVICES[fields["svc"]]["roku"],
        "id": fields["id"],
        "title": fields.get("t") or fields["id"],
        "media_type": MEDIA_TYPES.get(fields.get("type"), "movie"),
    }

def record_from_card(card):
    """A record for a card cached in cards.json before cards held their own records, or None."""
    if "app" not in card: # Learned from Jellyfin: {"id", "title", "type"} with a Jellyfin item type
        svc = "jellyfin"
        kind = {"Movie": "movie", "Episode": "episode", "Series": "show"}.get(card.get("type"), "movie")
    else:
        svc = next((name for name, s in config.SERVICES.items() if s["roku"] == card["app"]), None)
        kind = {"series": "show"}.get(card.get("media_type"), card.get("media_type") or "movie")
    if not svc:
        return None
    title = card.get("title", "").replace(";", ",")
    return f"v1;svc={svc};type={kind};id={card['id']};t={title}"

def fields_of(card):
    """The record fields for a cards.json entry, or None."""
    record = record_from_card(card)
    return parse(record) if record else None

def encode(text):
    """The bytes for user memory: an NDEF message TLV holding one text record, then the terminator."""
    payload = b"\x02en" + text.encode() # Status byte (UTF-8, 2-letter language), language, text
    if len(payload) > 250:
        raise ValueError("Record is too long for one card")
    record = bytes((0xD1, 1, len(payload))) + b"T" + payload # Short well-known record, type "T"
    return bytes((0x03, len(record))) + record + b"\xfe"

def decode(memory):
    """Returns ("more", None) if more memory is needed, else ("done", text or None)."""
    i = 0
    while i < len(memory):
        tag = memory[i]
        if tag == 0x00: # Padding
            i += 1
            continue
        if tag == 0xFE: # Terminator: no NDEF message
            return "done", None
        if i + 2 > len(memory):
            return "more", None
        length, start = memory[i + 1], i + 2
        if length == 0xFF: # 3-byte length form
            if i + 4 > len(memory):
                return "more", None
            length, start = (memory[i + 2] << 8) | memory[i + 3], i + 4
        if start + length > len(memory):
            return ("more", None) if start + length <= MAX_BYTES else ("done", None)
        if tag == 0x03:
            return "done", _text(memory[start:start + length])
        i = start + length # Skip lock and memory control TLVs
    return "more", None

def _text(message):
    """The text of the first record if it's an NDEF text record, else None."""
    if len(message) < 3:
        return None
    header, type_len = message[0], message[1]
    if header & 0x10: # Short record: 1-byte payload length
        payload_len, i = message[2], 3
    else:
        if len(message) < 6:
            return None
        payload_len, i = int.from_bytes(message[2:6], "big"), 6
    id_len = 0
    if header & 0x08:
        id_len, i = message[i], i + 1
    record_type, i = message[i:i + type_len], i + type_len + id_len
    if header & 0x07 != 1 or record_type != b"T":
        return None
    payload = message[i:i + payload_len]
    if not payload:
        return None
    try:
        return bytes(payload[1 + (payload[0] & 0x3F):]).decode()
    except UnicodeError:
        return None

def read_text(reader):
    """The text record on the card on the reader, or None (blank or not an NDEF card)."""
    memory = bytearray()
    while len(memory) < MAX_BYTES:
        memory += reader.read_pages(FIRST_PAGE + len(memory) // 4)
        status, text = decode(memory)
        if status == "done":
            return text
    return None

def write_text(reader, text):
    """Writes text to the card on the reader as its only record, then reads it back to check.

    The first page is blanked first and written last, so a card pulled away
    halfway reads as blank rather than as half a record.
    """
    cc = reader.read_pages(3)[:4]
    if cc[0] != 0xE1:
        if any(cc):
            raise RuntimeError("This card isn't NDEF-formatted. Use an NTAG215 card.")
        reader.write_page(3, CC_NTAG215) # One-time format of a factory-blank tag
        cc = CC_NTAG215
    data = encode(text)
    data += b"\x00" * (-len(data) % 4)
    if len(data) > cc[2] * 8:
        raise RuntimeError("The record doesn't fit on this card. Use an NTAG215.")
    reader.write_page(FIRST_PAGE, b"\x03\x00\xfe\x00") # Empty NDEF message while writing
    for offset in range(4, len(data), 4):
        reader.write_page(FIRST_PAGE + offset // 4, data[offset:offset + 4])
    reader.write_page(FIRST_PAGE, data[:4])
    if read_text(reader) != text:
        raise RuntimeError("The card didn't read back what was written")
