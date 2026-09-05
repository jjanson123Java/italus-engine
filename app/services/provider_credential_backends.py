from __future__ import annotations

import ctypes
import os
from functools import lru_cache
import shutil
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Mapping


_PROVIDER_ENV: Mapping[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_MAC_KEYCHAIN_SERVICE = b"com.italus.provider-credential"
_ERR_SEC_ITEM_NOT_FOUND = -25300


class CredentialBackendError(RuntimeError):
    """Raised when the selected trusted credential backend cannot complete an operation."""


def _truthy_environment(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def deployment_mode() -> str:
    """Return the trusted runtime deployment mode.

    Desktop is the compatibility default for the packaged/local Italus application.
    Server and development environment-credential modes must be selected explicitly.
    """
    mode = str(os.environ.get("ITALUS_DEPLOYMENT_MODE") or "desktop").strip().lower()
    if mode not in {"desktop", "server", "development"}:
        raise CredentialBackendError(
            "ITALUS_DEPLOYMENT_MODE must be one of: desktop, server, development."
        )
    return mode


def _config_root() -> Path:
    override = str(os.environ.get("ITALUS_CONFIG_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".italus").resolve()


class CredentialStore:
    source = "unavailable"
    managed_by_application = False
    interactive_management_available = False

    def available(self) -> bool:
        return False

    def read(self, provider_id: str) -> str | None:
        raise CredentialBackendError("The selected credential backend is unavailable.")

    def write(self, provider_id: str, secret: str) -> None:
        raise CredentialBackendError("The selected credential backend is unavailable.")

    def delete(self, provider_id: str) -> None:
        raise CredentialBackendError("The selected credential backend is unavailable.")


class UnavailableCredentialStore(CredentialStore):
    def __init__(self, reason: str):
        self.reason = str(reason or "The selected credential backend is unavailable.").strip()

    def read(self, provider_id: str) -> str | None:
        raise CredentialBackendError(self.reason)

    def write(self, provider_id: str, secret: str) -> None:
        raise CredentialBackendError(self.reason)

    def delete(self, provider_id: str) -> None:
        raise CredentialBackendError(self.reason)


class EnvironmentCredentialStore(CredentialStore):
    source = "environment"
    managed_by_application = False
    interactive_management_available = False

    def __init__(self, mode: str):
        self.mode = mode

    def available(self) -> bool:
        return True

    def read(self, provider_id: str) -> str | None:
        environment_name = _PROVIDER_ENV.get(provider_id)
        if not environment_name:
            raise CredentialBackendError(f"Unsupported provider_id: {provider_id}")
        value = str(os.environ.get(environment_name) or "").strip()
        return value or None

    def write(self, provider_id: str, secret: str) -> None:
        raise CredentialBackendError(
            "This deployment uses environment-managed provider credentials. "
            "Change the secret outside Italus."
        )

    def delete(self, provider_id: str) -> None:
        raise CredentialBackendError(
            "This deployment uses environment-managed provider credentials. "
            "Remove the secret outside Italus."
        )


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class WindowsDpapiCredentialStore(CredentialStore):
    source = "windows_dpapi"
    managed_by_application = True
    interactive_management_available = True

    def available(self) -> bool:
        return os.name == "nt"

    def _credential_path(self, provider_id: str) -> Path:
        return _config_root() / "credentials" / f"{provider_id}.dpapi"

    def _windows_crypto(self):
        if os.name != "nt":
            raise CredentialBackendError(
                "Windows DPAPI credential storage is unavailable on this platform."
            )

        crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
        kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)

        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DATA_BLOB),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DATA_BLOB),
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL

        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DATA_BLOB),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DATA_BLOB),
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL

        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        return crypt32, kernel32

    @staticmethod
    def _blob_from_bytes(data: bytes) -> tuple[_DATA_BLOB, object]:
        if not data:
            raise CredentialBackendError("Credential payload is empty.")
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        blob = _DATA_BLOB(
            len(data),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
        )
        return blob, buffer

    def _protect(self, data: bytes) -> bytes:
        crypt32, kernel32 = self._windows_crypto()
        input_blob, input_buffer = self._blob_from_bytes(data)
        output_blob = _DATA_BLOB()

        try:
            ok = crypt32.CryptProtectData(
                ctypes.byref(input_blob),
                "Italus provider credential",
                None,
                None,
                None,
                _CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output_blob),
            )
            if not ok:
                error = ctypes.get_last_error()
                raise CredentialBackendError(
                    f"Windows DPAPI could not protect the provider credential (error {error})."
                )
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            for index in range(len(input_buffer)):
                input_buffer[index] = 0
            if bool(output_blob.pbData):
                kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))

    def _unprotect(self, data: bytes) -> str:
        crypt32, kernel32 = self._windows_crypto()
        input_blob, input_buffer = self._blob_from_bytes(data)
        output_blob = _DATA_BLOB()
        description = wintypes.LPWSTR()

        try:
            ok = crypt32.CryptUnprotectData(
                ctypes.byref(input_blob),
                ctypes.byref(description),
                None,
                None,
                None,
                _CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output_blob),
            )
            if not ok:
                error = ctypes.get_last_error()
                raise CredentialBackendError(
                    f"Windows DPAPI could not read the stored provider credential (error {error})."
                )
            plain = ctypes.string_at(output_blob.pbData, output_blob.cbData)
            return plain.decode("utf-8")
        finally:
            for index in range(len(input_buffer)):
                input_buffer[index] = 0
            if bool(output_blob.pbData):
                kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))
            if description:
                kernel32.LocalFree(ctypes.cast(description, ctypes.c_void_p))

    def read(self, provider_id: str) -> str | None:
        if not self.available():
            raise CredentialBackendError(
                "Windows DPAPI credential storage is unavailable on this platform."
            )
        path = self._credential_path(provider_id)
        if not path.exists():
            return None
        try:
            secret = self._unprotect(path.read_bytes()).strip()
        except OSError as exc:
            raise CredentialBackendError(
                "Windows DPAPI could not read the stored provider credential."
            ) from exc
        return secret or None

    def write(self, provider_id: str, secret: str) -> None:
        if not self.available():
            raise CredentialBackendError(
                "Windows DPAPI credential storage is unavailable on this platform."
            )
        encoded = secret.encode("utf-8")
        encrypted = self._protect(encoded)
        path = self._credential_path(provider_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        try:
            temporary.write_bytes(encrypted)
            os.replace(temporary, path)
        except OSError as exc:
            raise CredentialBackendError(
                "Windows DPAPI could not store the provider credential."
            ) from exc
        finally:
            if temporary.exists():
                temporary.unlink()

    def delete(self, provider_id: str) -> None:
        path = self._credential_path(provider_id)
        if not path.exists():
            return
        try:
            path.unlink()
        except OSError as exc:
            raise CredentialBackendError(
                "Windows DPAPI could not remove the stored provider credential."
            ) from exc


class MacKeychainCredentialStore(CredentialStore):
    source = "mac_keychain"
    managed_by_application = True
    interactive_management_available = True

    def available(self) -> bool:
        return sys.platform == "darwin"

    def _frameworks(self):
        if sys.platform != "darwin":
            raise CredentialBackendError(
                "Apple Keychain credential storage is unavailable on this platform."
            )

        security = ctypes.CDLL(
            "/System/Library/Frameworks/Security.framework/Security"
        )
        core_foundation = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )

        security.SecKeychainFindGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        security.SecKeychainFindGenericPassword.restype = ctypes.c_int32

        security.SecKeychainAddGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        security.SecKeychainAddGenericPassword.restype = ctypes.c_int32

        security.SecKeychainItemModifyAttributesAndData.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32

        security.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
        security.SecKeychainItemDelete.restype = ctypes.c_int32

        security.SecKeychainItemFreeContent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        security.SecKeychainItemFreeContent.restype = ctypes.c_int32

        core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
        core_foundation.CFRelease.restype = None
        return security, core_foundation

    @staticmethod
    def _account(provider_id: str) -> bytes:
        return provider_id.encode("utf-8")

    def _find_item(self, provider_id: str):
        security, core_foundation = self._frameworks()
        account = self._account(provider_id)
        password_length = ctypes.c_uint32()
        password_data = ctypes.c_void_p()
        item_ref = ctypes.c_void_p()

        status = security.SecKeychainFindGenericPassword(
            None,
            len(_MAC_KEYCHAIN_SERVICE),
            _MAC_KEYCHAIN_SERVICE,
            len(account),
            account,
            ctypes.byref(password_length),
            ctypes.byref(password_data),
            ctypes.byref(item_ref),
        )
        return (
            security,
            core_foundation,
            status,
            password_length,
            password_data,
            item_ref,
        )

    def read(self, provider_id: str) -> str | None:
        (
            security,
            core_foundation,
            status,
            password_length,
            password_data,
            item_ref,
        ) = self._find_item(provider_id)

        if status == _ERR_SEC_ITEM_NOT_FOUND:
            return None
        if status != 0:
            raise CredentialBackendError(
                f"Apple Keychain could not read the provider credential (OSStatus {status})."
            )

        try:
            value = ctypes.string_at(password_data, password_length.value)
            return value.decode("utf-8").strip() or None
        finally:
            if password_data:
                security.SecKeychainItemFreeContent(None, password_data)
            if item_ref:
                core_foundation.CFRelease(item_ref)

    def write(self, provider_id: str, secret: str) -> None:
        secret_bytes = secret.encode("utf-8")
        secret_buffer = ctypes.create_string_buffer(secret_bytes)
        (
            security,
            core_foundation,
            status,
            _password_length,
            password_data,
            item_ref,
        ) = self._find_item(provider_id)

        try:
            if password_data:
                security.SecKeychainItemFreeContent(None, password_data)

            if status == 0:
                update_status = security.SecKeychainItemModifyAttributesAndData(
                    item_ref,
                    None,
                    len(secret_bytes),
                    ctypes.cast(secret_buffer, ctypes.c_void_p),
                )
                if update_status != 0:
                    raise CredentialBackendError(
                        "Apple Keychain could not replace the provider credential "
                        f"(OSStatus {update_status})."
                    )
                return

            if status != _ERR_SEC_ITEM_NOT_FOUND:
                raise CredentialBackendError(
                    "Apple Keychain could not inspect the provider credential "
                    f"(OSStatus {status})."
                )

            account = self._account(provider_id)
            new_item_ref = ctypes.c_void_p()
            add_status = security.SecKeychainAddGenericPassword(
                None,
                len(_MAC_KEYCHAIN_SERVICE),
                _MAC_KEYCHAIN_SERVICE,
                len(account),
                account,
                len(secret_bytes),
                ctypes.cast(secret_buffer, ctypes.c_void_p),
                ctypes.byref(new_item_ref),
            )
            if add_status != 0:
                raise CredentialBackendError(
                    f"Apple Keychain could not store the provider credential (OSStatus {add_status})."
                )
            if new_item_ref:
                core_foundation.CFRelease(new_item_ref)
        finally:
            if item_ref:
                core_foundation.CFRelease(item_ref)
            for index in range(len(secret_buffer)):
                secret_buffer[index] = 0

    def delete(self, provider_id: str) -> None:
        (
            security,
            core_foundation,
            status,
            _password_length,
            password_data,
            item_ref,
        ) = self._find_item(provider_id)

        if status == _ERR_SEC_ITEM_NOT_FOUND:
            return
        if status != 0:
            raise CredentialBackendError(
                f"Apple Keychain could not inspect the provider credential (OSStatus {status})."
            )

        try:
            if password_data:
                security.SecKeychainItemFreeContent(None, password_data)
            delete_status = security.SecKeychainItemDelete(item_ref)
            if delete_status != 0:
                raise CredentialBackendError(
                    f"Apple Keychain could not remove the provider credential (OSStatus {delete_status})."
                )
        finally:
            if item_ref:
                core_foundation.CFRelease(item_ref)


class LinuxSecretServiceCredentialStore(CredentialStore):
    source = "linux_secret_service"
    managed_by_application = True
    interactive_management_available = True

    def __init__(self):
        self._secret_tool = shutil.which("secret-tool")

    def available(self) -> bool:
        return sys.platform.startswith("linux") and bool(self._secret_tool)

    def _require_tool(self) -> str:
        if not self.available() or not self._secret_tool:
            raise CredentialBackendError(
                "Linux Secret Service credential storage requires the 'secret-tool' "
                "client and an available Secret Service/keyring session."
            )
        return self._secret_tool

    @staticmethod
    def _attributes(provider_id: str) -> list[str]:
        return ["application", "italus", "provider", provider_id]

    def read(self, provider_id: str) -> str | None:
        tool = self._require_tool()
        completed = subprocess.run(
            [tool, "lookup", *self._attributes(provider_id)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode == 1 and not completed.stderr.strip():
            return None
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise CredentialBackendError(
                "Linux Secret Service could not read the provider credential"
                + (f": {detail}" if detail else ".")
            )
        value = completed.stdout.decode("utf-8").strip()
        return value or None

    def write(self, provider_id: str, secret: str) -> None:
        tool = self._require_tool()
        secret_input = bytearray((secret + "\n").encode("utf-8"))
        try:
            completed = subprocess.run(
                [
                    tool,
                    "store",
                    "--label=Italus provider credential",
                    *self._attributes(provider_id),
                ],
                input=bytes(secret_input),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        finally:
            for index in range(len(secret_input)):
                secret_input[index] = 0

        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise CredentialBackendError(
                "Linux Secret Service could not store the provider credential"
                + (f": {detail}" if detail else ".")
            )

    def delete(self, provider_id: str) -> None:
        tool = self._require_tool()
        completed = subprocess.run(
            [tool, "clear", *self._attributes(provider_id)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode == 1 and not completed.stderr.strip():
            return
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise CredentialBackendError(
                "Linux Secret Service could not remove the provider credential"
                + (f": {detail}" if detail else ".")
            )


@lru_cache(maxsize=1)
def active_credential_store() -> CredentialStore:
    """Select exactly one trusted credential store for this process.

    No fallback is attempted. If the selected backend is unavailable, callers receive
    an unavailable store and must fail closed.
    """
    try:
        mode = deployment_mode()
    except CredentialBackendError as exc:
        return UnavailableCredentialStore(str(exc))

    if mode == "desktop":
        if os.name == "nt":
            store: CredentialStore = WindowsDpapiCredentialStore()
        elif sys.platform == "darwin":
            store = MacKeychainCredentialStore()
        elif sys.platform.startswith("linux"):
            store = LinuxSecretServiceCredentialStore()
        else:
            return UnavailableCredentialStore(
                f"No trusted desktop credential backend is defined for platform {sys.platform}."
            )
        if not store.available():
            return UnavailableCredentialStore(
                f"The trusted {store.source} credential backend is unavailable."
            )
        return store

    if mode == "server":
        provider = str(
            os.environ.get("ITALUS_SERVER_CREDENTIAL_PROVIDER") or ""
        ).strip().lower()
        if provider != "environment":
            return UnavailableCredentialStore(
                "Server credential mode requires "
                "ITALUS_SERVER_CREDENTIAL_PROVIDER=environment."
            )
        return EnvironmentCredentialStore(mode="server")

    if not _truthy_environment("ITALUS_ENABLE_DEVELOPMENT_ENV_CREDENTIALS"):
        return UnavailableCredentialStore(
            "Development environment credentials are disabled. "
            "Set ITALUS_ENABLE_DEVELOPMENT_ENV_CREDENTIALS=true only for an explicitly "
            "approved development runtime."
        )
    return EnvironmentCredentialStore(mode="development")
