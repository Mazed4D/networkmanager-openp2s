from __future__ import annotations

import base64
import hashlib
import html
import http.server
import json
import logging
import secrets
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

ENTRA_LOGIN_HOSTS = frozenset(
    {
        "login.microsoftonline.com",
        "login.microsoftonline.us",
        "login.partner.microsoftonline.cn",
        "login-us.microsoftonline.de",
        "login.microsoftonline.de",
        "login.usgovcloudapi.net",
        "login.chinacloudapi.cn",
    }
)

SIGN_IN_TIMEOUT = 300
EXPIRY_MARGIN = 120

SUCCESS_PAGE = (
    "<!doctype html><meta charset=utf-8><title>VPN sign-in</title>"
    "<body style='font:15px system-ui;padding:3rem'><h1>Signed in</h1>"
    "<p>You can close this tab; the VPN is connecting.</p>"
)


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class Client:
    authority: str
    client_id: str
    scope: str

    @property
    def key(self) -> str:
        return f"{self.authority}|{self.client_id}|{self.scope}"


@dataclass
class Token:
    access_token: str
    expires_at: float
    account: str | None = None

    def fresh(self) -> bool:
        return time.time() < self.expires_at - EXPIRY_MARGIN


class SecretStore:
    def __init__(self) -> None:
        self._memory: dict[str, str] = {}
        try:
            import gi

            gi.require_version("Secret", "1")
            from gi.repository import Secret

            self._secret = Secret
            self._schema = Secret.Schema.new(
                "org.freedesktop.NetworkManager.openp2s.RefreshToken",
                Secret.SchemaFlags.NONE,
                {"client": Secret.SchemaAttributeType.STRING},
            )
        except (ImportError, ValueError) as error:
            log.warning("Secret Service unavailable, sign-in will not persist: %s", error)
            self._secret = None

    def load(self, key: str) -> str | None:
        if self._secret:
            try:
                return self._secret.password_lookup_sync(self._schema, {"client": key}, None)
            except Exception as error:
                log.warning("could not read the stored session: %s", error)
        return self._memory.get(key)

    def save(self, key: str, value: str) -> None:
        self._memory[key] = value
        if self._secret:
            try:
                self._secret.password_store_sync(
                    self._schema,
                    {"client": key},
                    self._secret.COLLECTION_DEFAULT,
                    "VPN sign-in (nm-openp2s)",
                    value,
                    None,
                )
            except Exception as error:
                log.warning("could not store the session in the keyring: %s", error)

    def clear(self, key: str | None = None) -> None:
        if key:
            self._memory.pop(key, None)
        else:
            self._memory.clear()
        if self._secret:
            attributes = {"client": key} if key else {}
            try:
                self._secret.password_clear_sync(self._schema, attributes, None)
            except Exception as error:
                log.warning("could not clear the stored session: %s", error)


def _token_request(client: Client, form: dict[str, str]) -> dict:
    body = urllib.parse.urlencode({"client_id": client.client_id, **form}).encode()
    request = urllib.request.Request(
        f"{client.authority}/oauth2/v2.0/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.load(error)
            message = detail.get("error_description") or detail.get("error") or str(error)
        except ValueError:
            message = str(error)
        raise AuthError(message.splitlines()[0]) from None
    except (urllib.error.URLError, OSError) as error:
        raise AuthError(f"could not reach Microsoft Entra: {error}") from None


def _account_from_id_token(id_token: str | None) -> str | None:
    if not id_token:
        return None
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return claims.get("preferred_username") or claims.get("upn") or claims.get("email")
    except (IndexError, ValueError):
        return None


def _scopes(client: Client) -> str:
    return f"{client.scope} offline_access openid profile"


def refresh(client: Client, refresh_token: str) -> tuple[Token, str | None]:
    result = _token_request(
        client,
        {"grant_type": "refresh_token", "refresh_token": refresh_token, "scope": _scopes(client)},
    )
    return _to_token(result), result.get("refresh_token")


def _to_token(result: dict) -> Token:
    access = result.get("access_token")
    if not access:
        raise AuthError("Microsoft Entra returned no access token")
    return Token(
        access_token=access,
        expires_at=time.time() + int(result.get("expires_in", 3600)),
        account=_account_from_id_token(result.get("id_token")),
    )


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" not in query and "error" not in query:
            self.send_response(404)
            self.end_headers()
            return
        self.server.result = {k: v[0] for k, v in query.items()}
        ok = "code" in query
        body = SUCCESS_PAGE if ok else (
            "<!doctype html><meta charset=utf-8><title>VPN sign-in</title>"
            f"<body style='font:15px system-ui;padding:3rem'><h1>Sign-in failed</h1>"
            f"<p>{html.escape(query.get('error_description', query.get('error', ['']))[0])}</p>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())
        self.server.done.set()

    def log_message(self, format: str, *args: object) -> None:
        pass


def _loopback_servers() -> list[http.server.HTTPServer]:
    done = threading.Event()
    v4 = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    servers = [v4]
    try:

        class V6(http.server.HTTPServer):
            address_family = socket.AF_INET6

        servers.append(V6(("::1", v4.server_address[1]), _CallbackHandler))
    except OSError:
        pass
    for server in servers:
        server.done = done
        server.result = None
        server.timeout = 0.5
    return servers


def open_browser(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ENTRA_LOGIN_HOSTS:
        raise AuthError("refusing to open a non-Entra sign-in URL")
    try:
        subprocess.run(["xdg-open", url], check=True, timeout=15,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as error:
        raise AuthError(f"could not open a browser for sign-in: {error}") from None


def interactive(client: Client, login_hint: str | None = None, opener=open_browser) -> tuple[Token, str | None]:
    servers = _loopback_servers()
    port = servers[0].server_address[1]
    redirect_uri = f"http://localhost:{port}"
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)

    params = {
        "client_id": client.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": _scopes(client),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint
    url = f"{client.authority}/oauth2/v2.0/authorize?{urllib.parse.urlencode(params)}"

    threads = [threading.Thread(target=_serve_until, args=(s,), daemon=True) for s in servers]
    for thread in threads:
        thread.start()
    try:
        opener(url)
        if not servers[0].done.wait(SIGN_IN_TIMEOUT):
            raise AuthError("browser sign-in timed out")
    finally:
        for server in servers:
            server.done.set()
        for thread in threads:
            thread.join(2)
        for server in servers:
            server.server_close()

    result = next((s.result for s in servers if s.result), None)
    if not result:
        raise AuthError("browser sign-in did not complete")
    if result.get("state") != state:
        raise AuthError("sign-in response did not match this request (state mismatch)")
    if "error" in result:
        raise AuthError(result.get("error_description", result["error"]).splitlines()[0])

    token_result = _token_request(
        client,
        {
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "scope": _scopes(client),
        },
    )
    return _to_token(token_result), token_result.get("refresh_token")


def _serve_until(server: http.server.HTTPServer) -> None:
    while not server.done.is_set():
        server.handle_request()


class Authenticator:
    def __init__(self, store: SecretStore | None = None, opener=open_browser) -> None:
        self._store = store or SecretStore()
        self._opener = opener
        self._tokens: dict[str, Token] = {}
        self._accounts: dict[str, str] = {}
        self._lock = threading.Lock()

    def token(self, client: Client, interactive_allowed: bool = True, force_refresh: bool = False) -> Token:
        with self._lock:
            cached = self._tokens.get(client.key)
            if cached and cached.fresh() and not force_refresh:
                return cached

            refresh_token = self._store.load(client.key)
            if refresh_token:
                try:
                    token, rotated = refresh(client, refresh_token)
                    return self._remember(client, token, rotated)
                except AuthError as error:
                    log.info("silent sign-in failed, falling back to the browser: %s", error)

            if not interactive_allowed:
                raise AuthError("not signed in")
            log.info("opening the browser for Microsoft Entra sign-in")
            token, new_refresh = interactive(client, self._accounts.get(client.key), self._opener)
            return self._remember(client, token, new_refresh)

    def _remember(self, client: Client, token: Token, refresh_token: str | None) -> Token:
        self._tokens[client.key] = token
        if token.account:
            self._accounts[client.key] = token.account
        if refresh_token:
            self._store.save(client.key, refresh_token)
        return token

    def forget(self, client: Client | None = None) -> None:
        with self._lock:
            if client:
                self._tokens.pop(client.key, None)
                self._store.clear(client.key)
            else:
                self._tokens.clear()
                self._store.clear()
