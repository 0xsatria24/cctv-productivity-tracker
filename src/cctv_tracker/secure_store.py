"""Atomic local configuration, with OS-bound protection for camera secrets."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _dpapi(data, decrypt=False):
    class Blob(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), buffer), Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    call = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    call.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    call.restype = wintypes.BOOL
    if not call(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise RuntimeError('Camera credentials cannot be unlocked by this OS account')
    try:
        return ctypes.string_at(target.data, target.length)
    finally:
        kernel.LocalFree(target.data)


class SecureStore:
    """Windows DPAPI CurrentUser; Unix encrypted file with a private local key."""
    def __init__(self, path):
        self.path = Path(path)

    def _unix_cipher(self):
        from cryptography.fernet import Fernet
        key = self.path.with_suffix('.key')
        if not key.exists():
            if self.path.exists():
                raise RuntimeError('Camera credential key is missing')
            atomic_write(key, Fernet.generate_key())
        if key.stat().st_mode & 0o077:
            raise RuntimeError('Credential key must have mode 0600')
        return Fernet(key.read_bytes())

    def encode(self, value):
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        data = _dpapi(raw) if os.name == 'nt' else self._unix_cipher().encrypt(raw)
        return (b'DPAPI1\n' if os.name == 'nt' else b'FERNET1\n') + base64.b64encode(data)

    def decode(self, payload):
        marker, encoded = payload.split(b'\n', 1)
        expected = b'DPAPI1' if os.name == 'nt' else b'FERNET1'
        if marker != expected:
            raise ValueError('Backup credentials require the original OS/account')
        data = base64.b64decode(encoded, validate=True)
        return json.loads(_dpapi(data, True) if os.name == 'nt' else self._unix_cipher().decrypt(data))

    def load(self):
        return self.decode(self.path.read_bytes()) if self.path.exists() else {'version': 1, 'cameras': []}

    def save(self, value):
        atomic_write(self.path, self.encode(value))
