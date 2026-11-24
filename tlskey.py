# tlskey.py
# The player's own RSA key and self-signed certificate, made on the board, so it
# can pair with a Google TV (see googletv.py). MicroPython has big integers and
# SHA-256 but no RSA, so this is a small RSA key generator and X.509 writer.
# 2048-bit like Google's own remote apps; it takes a minute or two on the ESP32-S3, once,
# so key_steps() does it a little at a time while the player keeps answering taps and the app.
import hashlib
import os

E = 65537
SHA256_RSA = b"\x06\x09\x2a\x86\x48\x86\xf7\x0d\x01\x01\x0b" # OID sha256WithRSAEncryption
RSA = b"\x06\x09\x2a\x86\x48\x86\xf7\x0d\x01\x01\x01" # OID rsaEncryption
COMMON_NAME = b"\x06\x03\x55\x04\x03"
DIGEST_INFO = b"\x30\x31\x30\x0d\x06\x09\x60\x86\x48\x01\x65\x03\x04\x02\x01\x05\x00\x04\x20" # PKCS#1 SHA-256 prefix

def _small_primes(limit):
    sieve = bytearray(b"\x01" * limit)
    for i in range(2, int(limit ** 0.5) + 1):
        if sieve[i]:
            for j in range(i * i, limit, i):
                sieve[j] = 0
    return [i for i in range(3, limit) if sieve[i]]

SMALL_PRIMES = _small_primes(2000)

def _random(nbytes):
    return int.from_bytes(os.urandom(nbytes), "big")

def _probably_prime(n, rounds=5):
    """Miller-Rabin. The first round uses base 2, which rules out nearly every composite."""
    d, s = n - 1, 0
    while not d & 1:
        d >>= 1
        s += 1
    for r in range(rounds):
        a = 2 if r == 0 else _random(64) % (n - 3) + 2
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True

def _prime_steps(bits, out):
    """Appends a random prime with its top two bits set (so two make a full-size modulus) to out, yielding as it goes."""
    while True:
        n = _random(bits // 8) | (3 << (bits - 2)) | 1
        residues = [n % p for p in SMALL_PRIMES]
        yield
        for delta in range(0, 4000, 2): # Walk odd numbers, skipping any with a small factor
            for i in range(len(SMALL_PRIMES)):
                if (residues[i] + delta) % SMALL_PRIMES[i] == 0:
                    break
            else:
                candidate = n + delta
                if candidate % E != 1:
                    yield
                    if _probably_prime(candidate):
                        out.append(candidate)
                        return

def _inverse(a, m):
    r0, r1, t0, t1 = m, a % m, 0, 1
    while r1:
        q = r0 // r1
        r0, r1 = r1, r0 - q * r1
        t0, t1 = t1, t0 - q * t1
    return t0 % m

def key_steps(out, bits=2048):
    """Makes a new RSA key a little per step and appends it to out:
    (n, e, d, p, q, d mod p-1, d mod q-1, q^-1 mod p)."""
    primes = []
    while len(primes) < 2:
        yield from _prime_steps(bits // 2, primes)
        if len(primes) == 2 and primes[0] == primes[1]:
            primes.pop()
    p, q = primes
    d = _inverse(E, (p - 1) * (q - 1))
    out.append((p * q, E, d, p, q, d % (p - 1), d % (q - 1), _inverse(q, p)))

def generate(bits=2048):
    """A new RSA key, all at once."""
    out = []
    for _ in key_steps(out, bits):
        pass
    return out[0]

def unsigned(n):
    """n as big-endian bytes with no leading zeros."""
    length, m = 0, n
    while m:
        m >>= 8
        length += 1
    return n.to_bytes(max(length, 1), "big")

def _tlv(tag, body):
    n = len(body)
    length = bytes([n]) if n < 0x80 else bytes([0x81, n]) if n < 0x100 else bytes([0x82, n >> 8, n & 0xFF])
    return bytes([tag]) + length + body

def _seq(*parts):
    return _tlv(0x30, b"".join(parts))

def _integer(n):
    b = unsigned(n)
    return _tlv(0x02, b"\x00" + b if b[0] & 0x80 else b)

def sign(key, data):
    """PKCS#1 v1.5 SHA-256 signature, using the CRT parts of the key."""
    n, _, _, p, q, dp, dq, qinv = key
    k = len(unsigned(n))
    t = DIGEST_INFO + hashlib.sha256(data).digest()
    m = int.from_bytes(b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t, "big")
    m1, m2 = pow(m, dp, p), pow(m, dq, q)
    return (m2 + (qinv * (m1 - m2) % p) * q).to_bytes(k, "big")

def certificate(key, name="NFC Movie Player"):
    """A self-signed X.509 v1 certificate (DER) for the key, valid 2020–2049."""
    algorithm = _seq(SHA256_RSA, b"\x05\x00")
    subject = _seq(_tlv(0x31, _seq(COMMON_NAME, _tlv(0x0C, name.encode()))))
    validity = _seq(_tlv(0x17, b"200101000000Z"), _tlv(0x17, b"491231235959Z"))
    public = _seq(_seq(RSA, b"\x05\x00"), _tlv(0x03, b"\x00" + _seq(_integer(key[0]), _integer(key[1]))))
    tbs = _seq(_integer(_random(8) | 1), algorithm, subject, validity, subject, public)
    return _seq(tbs, algorithm, _tlv(0x03, b"\x00" + sign(key, tbs)))

def private_key(key):
    """The key as PKCS#1 RSAPrivateKey DER."""
    return _seq(_integer(0), *[_integer(x) for x in key])

def _read(der, i):
    """(tag, content start, content end) of the DER element at i."""
    tag, length = der[i], der[i + 1]
    i += 2
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(der[i:i + count], "big")
        i += count
    return tag, i, i + length

def public_key(cert):
    """(n, e) of an X.509 certificate's RSA key."""
    _, i, _ = _read(cert, 0) # Certificate
    _, i, _ = _read(cert, i) # TBSCertificate
    if cert[i] == 0xA0: # Version
        i = _read(cert, i)[2]
    for _ in range(5): # Serial, signature algorithm, issuer, validity, subject
        i = _read(cert, i)[2]
    _, i, _ = _read(cert, i) # SubjectPublicKeyInfo
    i = _read(cert, i)[2] # Algorithm
    _, i, _ = _read(cert, i) # BIT STRING
    _, i, _ = _read(cert, i + 1) # RSAPublicKey, after the unused-bits byte
    _, start, end = _read(cert, i)
    n = int.from_bytes(cert[start:end], "big")
    _, start, e_end = _read(cert, end)
    return n, int.from_bytes(cert[start:e_end], "big")
