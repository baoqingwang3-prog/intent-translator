"""Read and provision the local TokenDance credential without a plaintext config file."""

from __future__ import annotations

import argparse
import ctypes
import os
import re
import sys
from ctypes import wintypes


JEV_CREDENTIAL_TARGET = "IntentTranslator:TokenDance:Jev"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_TOKEN_PATTERN = re.compile(r"^sk-[A-Za-z0-9_-]{20,512}$")


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FileTime),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _advapi32():
    if os.name != "nt":
        raise RuntimeError("Windows Credential Manager is only available on Windows")
    library = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    library.CredReadW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_Credential)),
    ]
    library.CredReadW.restype = wintypes.BOOL
    library.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
    library.CredWriteW.restype = wintypes.BOOL
    library.CredFree.argtypes = [ctypes.c_void_p]
    library.CredFree.restype = None
    return library


def read_jev_key() -> str | None:
    """Return the key for the current Windows user, or None when absent."""
    if os.name != "nt":
        return None
    library = _advapi32()
    pointer = ctypes.POINTER(_Credential)()
    if not library.CredReadW(JEV_CREDENTIAL_TARGET, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
            return None
        raise OSError(ctypes.get_last_error(), "Could not read Jev credential")
    try:
        credential = pointer.contents
        data = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return data.decode("utf-8")
    finally:
        library.CredFree(pointer)


def save_jev_key(key: str) -> None:
    """Store a single TokenDance key under the current Windows user."""
    key = key.strip().removeprefix("Bearer ").strip().strip("\"'")
    if not _TOKEN_PATTERN.fullmatch(key):
        raise ValueError("Expected one TokenDance sk- key")
    library = _advapi32()
    encoded = key.encode("utf-8")
    blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
    credential = _Credential()
    credential.Type = _CRED_TYPE_GENERIC
    credential.TargetName = JEV_CREDENTIAL_TARGET
    credential.CredentialBlobSize = len(encoded)
    credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = "intent-translator"
    if not library.CredWriteW(ctypes.byref(credential), 0):
        raise OSError(ctypes.get_last_error(), "Could not save Jev credential")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the local Jev credential")
    parser.add_argument("action", choices=("status", "set-stdin"))
    args = parser.parse_args(argv)
    if args.action == "status":
        print("configured" if read_jev_key() else "missing")
        return 0
    # Only use an explicit local pipe; never accept a key as a command argument.
    if sys.stdin.isatty():
        parser.error("pipe the key to set-stdin; command-line keys are not accepted")
    save_jev_key(sys.stdin.read())
    print("stored in Windows Credential Manager")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
