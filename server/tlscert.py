"""Self-signed Ed25519 TLS certificates without extra packages.

Every PC encrypts its sync traffic with TLS. The certificate is not checked against
a certificate authority: each PC knows the exact SHA-256 fingerprint of every other
PC's certificate (exchanged during pairing and signed by the administrator PC), and
a connection is dropped before anything is sent when the fingerprint does not match.
So a long validity and a fixed issuer are fine - only the key inside matters.
"""
import base64
import hashlib

import ed25519

_OID_ED25519 = b'\x06\x03\x2b\x65\x70'
_OID_CN = b'\x06\x03\x55\x04\x03'


def _len(n):
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    return bytes([0x80 | len(b)]) + b


def _tlv(tag, body):
    return bytes([tag]) + _len(len(body)) + body


def _seq(*parts):
    return _tlv(0x30, b''.join(parts))


def _int(n):
    b = n.to_bytes(max(1, (n.bit_length() + 8) // 8), 'big')
    return _tlv(0x02, b)


def _name(cn):
    return _seq(_tlv(0x31, _seq(_OID_CN, _tlv(0x0c, cn.encode('utf-8')))))


def _pem(kind, der):
    b64 = base64.encodebytes(der).decode('ascii').replace('\n', '')
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return f'-----BEGIN {kind}-----\n' + '\n'.join(lines) + f'\n-----END {kind}-----\n'


def make_cert(seed, common_name, serial):
    """(certificate PEM, private key PEM, certificate SHA-256 hex) for the Ed25519 key seed."""
    pub = ed25519.public_key(seed)
    alg = _seq(_OID_ED25519)
    validity = _seq(_tlv(0x17, b'200101000000Z'), _tlv(0x18, b'99991231235959Z'))
    spki = _seq(alg, _tlv(0x03, b'\x00' + pub))
    tbs = _seq(_tlv(0xa0, _int(2)), _int(serial), alg, _name(common_name), validity, _name(common_name), spki)
    cert = _seq(tbs, alg, _tlv(0x03, b'\x00' + ed25519.sign(seed, tbs, pub)))
    key = _seq(_int(0), alg, _tlv(0x04, _tlv(0x04, seed)))
    return _pem('CERTIFICATE', cert), _pem('PRIVATE KEY', key), hashlib.sha256(cert).hexdigest()


def fingerprint_der(der):
    return hashlib.sha256(der).hexdigest()
