"""Подпись Authenticode и версия файла средствами Windows (03.10, обновление установщиком).

Зачем: привилегированная операция `install-setup` (`privileged.py`) ЗАПУСКАЕТ
установщик с правами администратора — единственное исключение из правила «за
повышением ничего не исполняется». Исключение держится на трёх проверках, две
из них здесь: файл подписан, и подписал его НАШ сертификат (отпечаток из
закрытого списка), а версия файла новее стоящей программы.

⛔ Без PowerShell и без `signtool`: за UAC оболочек не бывает (правило
`privileged.py`), а `signtool` у клиники не стоит. Только WinVerifyTrust
(`wintrust.dll`), отпечаток подписанта — из цепочки, которую построила сама
проверка, и `version.dll` для номера версии.
⚠️ Отзыв сертификата не проверяется (`WTD_REVOKE_NONE`): клиника бывает без
интернета, а проверка, падающая офлайн, остановила бы обновления. Цепочка до
доверенного корня и целостность файла проверяются всегда.

⚠️ Предзагрузочный слой, как `privileged.py`: импортов проекта нет — модуль
зовётся в привилегированном процессе до того, как приложение существует.
"""
from __future__ import annotations

import sys

# WinVerifyTrust: «обычная» политика Authenticode
_GUID_GENERIC_VERIFY_V2 = (0x00AAC56B, 0xCD44, 0x11D0, (0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE))
_WTD_UI_NONE, _WTD_REVOKE_NONE, _WTD_CHOICE_FILE = 2, 0, 1
_WTD_STATEACTION_VERIFY, _WTD_STATEACTION_CLOSE = 1, 2
_WTD_REVOCATION_CHECK_NONE = 0x10
_CERT_SHA1_HASH_PROP_ID = 3


def _api():
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    class FILE_INFO(ctypes.Structure):
        _fields_ = [("cbStruct", wintypes.DWORD), ("pcwszFilePath", wintypes.LPCWSTR),
                    ("hFile", wintypes.HANDLE), ("pgKnownSubject", ctypes.POINTER(GUID))]

    class DATA(ctypes.Structure):
        _fields_ = [("cbStruct", wintypes.DWORD), ("pPolicyCallbackData", ctypes.c_void_p),
                    ("pSIPClientData", ctypes.c_void_p), ("dwUIChoice", wintypes.DWORD),
                    ("fdwRevocationChecks", wintypes.DWORD), ("dwUnionChoice", wintypes.DWORD),
                    ("pFile", ctypes.POINTER(FILE_INFO)), ("dwStateAction", wintypes.DWORD),
                    ("hWVTStateData", wintypes.HANDLE), ("pwszURLReference", wintypes.LPWSTR),
                    ("dwProvFlags", wintypes.DWORD), ("dwUIContext", wintypes.DWORD),
                    ("pSignatureSettings", ctypes.c_void_p)]

    class PROVIDER_CERT(ctypes.Structure):
        _fields_ = [("cbStruct", wintypes.DWORD), ("pCert", ctypes.c_void_p)]

    class PROVIDER_SGNR(ctypes.Structure):
        _fields_ = [("cbStruct", wintypes.DWORD), ("sftVerifyAsOf", wintypes.FILETIME),
                    ("csCertChain", wintypes.DWORD), ("pasCertChain", ctypes.POINTER(PROVIDER_CERT))]

    wintrust = ctypes.WinDLL("wintrust")
    crypt32 = ctypes.WinDLL("crypt32")
    wintrust.WinVerifyTrust.argtypes = [wintypes.HWND, ctypes.POINTER(GUID), ctypes.c_void_p]
    wintrust.WinVerifyTrust.restype = wintypes.LONG
    wintrust.WTHelperProvDataFromStateData.argtypes = [wintypes.HANDLE]
    wintrust.WTHelperProvDataFromStateData.restype = ctypes.c_void_p
    wintrust.WTHelperGetProvSignerFromChain.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL,
                                                         wintypes.DWORD]
    wintrust.WTHelperGetProvSignerFromChain.restype = ctypes.POINTER(PROVIDER_SGNR)
    crypt32.CertGetCertificateContextProperty.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                                          ctypes.POINTER(wintypes.DWORD)]
    crypt32.CertGetCertificateContextProperty.restype = wintypes.BOOL
    d1, d2, d3, d4 = _GUID_GENERIC_VERIFY_V2
    guid = GUID(d1, d2, d3, (ctypes.c_ubyte * 8)(*d4))
    return ctypes, wintypes, guid, FILE_INFO, DATA, wintrust, crypt32


def signer_thumbprint(path) -> str | None:
    """SHA-1 отпечаток сертификата, которым подписан файл, — ТОЛЬКО если подпись
    действительна (файл цел, цепочка до доверенного корня). Иначе None: нет
    подписи, файл тронут после подписи, сертификат не доверен, не Windows."""
    if sys.platform != "win32":
        return None
    try:
        ctypes, wintypes, guid, FILE_INFO, DATA, wintrust, crypt32 = _api()
    except (OSError, AttributeError):
        return None
    info = FILE_INFO(ctypes.sizeof(FILE_INFO), str(path), None, None)
    data = DATA()
    data.cbStruct = ctypes.sizeof(DATA)
    data.dwUIChoice = _WTD_UI_NONE
    data.fdwRevocationChecks = _WTD_REVOKE_NONE
    data.dwUnionChoice = _WTD_CHOICE_FILE
    data.pFile = ctypes.pointer(info)
    data.dwStateAction = _WTD_STATEACTION_VERIFY
    data.dwProvFlags = _WTD_REVOCATION_CHECK_NONE
    hwnd = wintypes.HWND(-1)           # INVALID_HANDLE_VALUE: человека не спрашивать
    try:
        if wintrust.WinVerifyTrust(hwnd, ctypes.byref(guid), ctypes.byref(data)) != 0:
            return None
        prov = wintrust.WTHelperProvDataFromStateData(data.hWVTStateData)
        if not prov:
            return None
        sgnr = wintrust.WTHelperGetProvSignerFromChain(prov, 0, False, 0)
        if not sgnr or sgnr.contents.csCertChain < 1:
            return None
        cert = sgnr.contents.pasCertChain[0].pCert
        size = wintypes.DWORD(20)
        buf = (ctypes.c_ubyte * 20)()
        if not crypt32.CertGetCertificateContextProperty(cert, _CERT_SHA1_HASH_PROP_ID, buf,
                                                          ctypes.byref(size)):
            return None
        return bytes(buf[: size.value]).hex().upper()
    finally:
        data.dwStateAction = _WTD_STATEACTION_CLOSE
        wintrust.WinVerifyTrust(hwnd, ctypes.byref(guid), ctypes.byref(data))


def file_version(path) -> tuple[int, int, int, int] | None:
    """Версия файла из ресурса VERSIONINFO (то, что Windows показывает в свойствах).
    None — ресурса нет или файл не читается."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class FIXED(ctypes.Structure):
        _fields_ = [("dwSignature", wintypes.DWORD), ("dwStrucVersion", wintypes.DWORD),
                    ("dwFileVersionMS", wintypes.DWORD), ("dwFileVersionLS", wintypes.DWORD)]

    try:
        ver = ctypes.WinDLL("version")
    except OSError:
        return None
    ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    ver.GetFileVersionInfoW.restype = wintypes.BOOL
    ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                   ctypes.POINTER(wintypes.UINT)]
    ver.VerQueryValueW.restype = wintypes.BOOL
    size = ver.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
        return None
    p, n = ctypes.c_void_p(), wintypes.UINT()
    if not ver.VerQueryValueW(buf, "\\", ctypes.byref(p), ctypes.byref(n)) or not p.value:
        return None
    f = FIXED.from_address(p.value)
    if f.dwSignature != 0xFEEF04BD:
        return None
    ms, ls = f.dwFileVersionMS, f.dwFileVersionLS
    return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
