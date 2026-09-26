"""Ed25519 digital signatures (RFC 8032) in pure Python - no extra packages needed.

Used to prove which PC made a change (every PC has its own key) and that a user or
permission change really comes from the administrator PC (the "authority" key).

Based on the reference algorithms of RFC 8032 section 5.1 with two speed-ups:
a dedicated point doubling and a precomputed table for multiplying the fixed base
point. Verification uses only public data. Signing is not constant-time (Python big
integers never are); on a company LAN the only party who could time a signature is
somebody already on the signing PC, which is outside the threat model.
"""
import hashlib
import os

p = 2 ** 255 - 19
q = 2 ** 252 + 27742317777372353535851937790883648493  # order of the base point
d = -121665 * pow(121666, p - 2, p) % p
SQRT_M1 = pow(2, (p - 1) // 4, p)


def _inv(x):
    return pow(x, p - 2, p)


def _add(P, Q):
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % p
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % p
    C = 2 * P[3] * Q[3] * d % p
    D = 2 * P[2] * Q[2] % p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % p, G * H % p, F * G % p, E * H % p)


def _double(P):
    A = P[0] * P[0] % p
    B = P[1] * P[1] % p
    C = 2 * P[2] * P[2] % p
    H = A + B
    E = H - (P[0] + P[1]) * (P[0] + P[1]) % p
    G = A - B
    F = C + G
    return (E * F % p, G * H % p, F * G % p, E * H % p)


_ZERO = (0, 1, 1, 0)
_gy = 4 * _inv(5) % p


def _recover_x(y, sign):
    if y >= p:
        return None
    x2 = (y * y - 1) * _inv(d * y * y + 1) % p
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (p + 3) // 8, p)
    if (x * x - x2) % p:
        x = x * SQRT_M1 % p
    if (x * x - x2) % p:
        return None
    if (x & 1) != sign:
        x = p - x
    return x


_gx = _recover_x(_gy, 0)
BASE = (_gx, _gy, 1, _gx * _gy % p)

# _TABLE[i][j] = j * 16^i * BASE, so [k]BASE needs only 64 additions.
_TABLE = []
_P = BASE
for _i in range(64):
    row = [_ZERO, _P]
    for _j in range(2, 16):
        row.append(_add(row[-1], _P))
    _TABLE.append(row)
    for _ in range(4):
        _P = _double(_P)
del _P, _i, _j


def _mul_base(k):
    R = _ZERO
    for i in range(64):
        R = _add(R, _TABLE[i][(k >> (4 * i)) & 15])
    return R


def _mul(k, P):
    table = [_ZERO, P]
    for _ in range(14):
        table.append(_add(table[-1], P))
    R = _ZERO
    for i in range(63, -1, -1):
        R = _double(_double(_double(_double(R))))
        R = _add(R, table[(k >> (4 * i)) & 15])
    return R


def _equal(P, Q):
    return (P[0] * Q[2] - Q[0] * P[2]) % p == 0 and (P[1] * Q[2] - Q[1] * P[2]) % p == 0


def _encode(P):
    zi = _inv(P[2])
    x, y = P[0] * zi % p, P[1] * zi % p
    return (y | ((x & 1) << 255)).to_bytes(32, 'little')


def _decode(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, 'little')
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % p)


def _hint(*parts):
    return int.from_bytes(hashlib.sha512(b''.join(parts)).digest(), 'little') % q


def _expand(seed):
    if len(seed) != 32:
        raise ValueError('Ed25519 private key must be 32 bytes')
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], 'little')
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def generate():
    """A new random private key (32-byte seed)."""
    return os.urandom(32)


def public_key(seed):
    a, _ = _expand(seed)
    return _encode(_mul_base(a))


def sign(seed, msg, pub=None):
    a, prefix = _expand(seed)
    A = pub or _encode(_mul_base(a))
    r = _hint(prefix, msg)
    R = _encode(_mul_base(r))
    s = (r + _hint(R, A, msg) * a) % q
    return R + s.to_bytes(32, 'little')


def verify(pub, msg, sig):
    """True only for a valid signature of msg by the owner of the public key pub."""
    try:
        if len(pub) != 32 or len(sig) != 64:
            return False
        A = _decode(pub)
        R = _decode(sig[:32])
        if A is None or R is None:
            return False
        s = int.from_bytes(sig[32:], 'little')
        if s >= q:
            return False
        k = _hint(sig[:32], pub, msg)
        return _equal(_mul_base(s), _add(R, _mul(k, A)))
    except (TypeError, ValueError):
        return False
