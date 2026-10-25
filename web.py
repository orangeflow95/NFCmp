# web.py
# Helpers for the player's tiny non-blocking HTTP servers (setup portal and link page).
import json
import socket

# color-scheme makes the page follow the phone's light or dark mode; .h is a hint, .e an error
PAGE_HEAD = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<meta name=color-scheme content="light dark"><title>{title}</title><style>:root{{color-scheme:light dark}}
body{{font-family:-apple-system,sans-serif;max-width:30em;margin:2em auto;padding:0 1em}}
.t{{font-size:1.1em;width:100%;padding:.6em;margin:.4em 0;box-sizing:border-box}}label{{display:inline-block;margin:.5em 1em .5em 0}}
.h{{color:#666;font-size:.9em;margin:.2em 0 1em}}h3{{margin:1.5em 0 .3em}}.e{{color:#c00}}
@media (prefers-color-scheme:dark){{.h{{color:#aaa}}.e{{color:#ff6b6b}}}}</style>"""

def listen(port):
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(socket.getaddrinfo("0.0.0.0", port)[0][-1])
    sock.listen(2)
    sock.setblocking(False)
    return sock

def accept(sock):
    """Returns a waiting client, or None."""
    try:
        client, _ = sock.accept()
    except OSError:
        return None
    client.settimeout(3)
    return client

def unquote(text):
    """Decodes a URL-encoded form value."""
    parts = text.replace("+", " ").split("%")
    out = bytearray(parts[0].encode())
    for part in parts[1:]:
        try:
            out.append(int(part[:2], 16))
            out.extend(part[2:].encode())
        except ValueError:
            out.extend(("%" + part).encode())
    return bytes(out).decode()

def quote(text):
    """URL-encodes a form value."""
    out = ""
    for byte in text.encode():
        char = chr(byte)
        out += char if byte < 128 and (char.isalpha() or char.isdigit() or char in "-_.~") else "%%%02X" % byte
    return out

def parse_form(text):
    fields = {}
    for pair in text.split("&"):
        key_value = pair.split("=", 1)
        if len(key_value) == 2:
            fields[unquote(key_value[0])] = unquote(key_value[1])
    return fields

def escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def read_request(client):
    """Returns (method, path, headers, form). The form merges the query string and a POSTed body."""
    data = client.recv(2048)
    while b"\r\n\r\n" not in data and len(data) < 8192:
        more = client.recv(1024)
        if not more:
            break
        data += more
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    parts = lines[0].split(" ")
    method, path = (parts[0], parts[1]) if len(parts) >= 3 else ("GET", "/")
    headers = {}
    for line in lines[1:]:
        key, _, value = line.partition(":")
        headers[key.strip().lower()] = value.strip()
    try:
        length = int(headers.get("content-length", "0"))
    except ValueError:
        length = 0
    while len(body) < length:
        more = client.recv(1024)
        if not more:
            break
        body += more
    path, _, query = path.partition("?")
    form = parse_form(query)
    if method == "POST":
        form.update(parse_form(body.decode()))
    return method, path, headers, form

def send_json(client, value):
    client.sendall(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n")
    client.sendall(json.dumps(value).encode())

def send(client, title="", body="", status="200 OK", headers=""):
    client.sendall(f"HTTP/1.0 {status}\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n{headers}\r\n".encode())
    if body:
        client.sendall((PAGE_HEAD.format(title=title) + body).encode())
