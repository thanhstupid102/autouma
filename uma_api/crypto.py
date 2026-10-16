import base64
import hashlib
import os
import random
import struct

import msgpack
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


__all__ = [
    "sm5",
    "make_md5_hex",
    "make_sid",
    "next_sid",
    "gen_key",
    "get_iv",
    "get_raw_udid",
    "pack",
    "unpack",
    "unpack_request",
]

SALT = b'co!=Y;(UQCGxJ_n82'
HEAD = bytes.fromhex('6b20e2ab6c311330f761d737ce3f3025750850665eea58b6372f8d2f57501eb344bdb7270a9067f5b63cd61f152cfb986cbfbf7a')


def sm5(data):
    h = hashlib.md5()
    h.update(data)
    h.update(SALT)
    return h.digest()


def make_md5_hex(text: str) -> str:
    # Gallop.Cryptographer.MakeMd5: UTF-8 text followed by the game's salt.
    return sm5(text.encode("utf-8")).hex()


def make_sid(vid, udid):
    return sm5((str(vid) + udid).encode())

def next_sid(sid):
    return sm5(sid.encode())

def gen_key():
    out = b''
    while len(out) < 32:
        out += format(random.randint(0, 65535), 'x').encode()
    return out[:32]

def get_iv(udid):
    return udid.replace('-', '').lower()[:16].encode()

def get_raw_udid(udid):
    return bytes.fromhex(udid.replace('-', '').lower())

def pack(sid, udid_raw, auth, payload, udid):
    key = gen_key()
    p = msgpack.packb(payload, use_bin_type=True)
    body = AES.new(key, AES.MODE_CBC, get_iv(udid)).encrypt(pad(struct.pack('<I', len(p)) + p, 16)) + key
    h = HEAD + sid + udid_raw + os.urandom(32)
    if auth: h += auth
    return base64.b64encode(struct.pack('<I', len(h)) + h + body)

def _decrypt_body(body, udid):
    key, cipher = body[-32:], body[:-32]
    p = unpad(AES.new(key, AES.MODE_CBC, get_iv(udid)).decrypt(cipher), 16)
    return msgpack.unpackb(p[4:4+struct.unpack('<I',p[:4])[0]], raw=False, strict_map_key=False)

def unpack(text, udid):
    raw = base64.b64decode(text)
    return _decrypt_body(raw, udid)

def unpack_request(text, udid):
    """Decode an OUTGOING request body produced by pack() -- used to recover the device
    fingerprint the account REGISTERED with from a captured request (cfg['body']). Unlike
    unpack() (a response), a request has a HEAD+sid+udid+auth header prefixed via a u32
    length, so skip that before the cipher: b64( <u32 len(h)> + h + cipher + key[-32:] )."""
    raw = base64.b64decode(text)
    hlen = struct.unpack('<I', raw[:4])[0]
    return _decrypt_body(raw[4 + hlen:], udid)
