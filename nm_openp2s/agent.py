from __future__ import annotations

import json
import logging
import os
import socket
import struct
import sys
import threading

from . import AGENT_SOCKET
from .entra import AuthError, Authenticator, Client
from .profile import ProfileError, validate_authority

log = logging.getLogger("nm-openp2s-agent")

SD_LISTEN_FDS_START = 3
MAX_REQUEST = 64 * 1024
IDLE_EXIT_SECONDS = 15 * 60


def socket_path(runtime_dir: str | None = None) -> str:
    return os.path.join(runtime_dir or os.environ["XDG_RUNTIME_DIR"], AGENT_SOCKET)


def _peer_uid(conn: socket.socket) -> int:
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", creds)
    return uid


def _client_from(request: dict) -> Client:
    try:
        authority = validate_authority(str(request["authority"]))
    except (KeyError, ProfileError) as error:
        raise AuthError(f"bad authority: {error}") from None
    client_id = str(request.get("client_id", ""))
    scope = str(request.get("scope", ""))
    if not client_id or not scope or len(client_id) > 200 or len(scope) > 400:
        raise AuthError("bad client_id or scope")
    return Client(authority=authority, client_id=client_id, scope=scope)


class Agent:
    def __init__(self, authenticator: Authenticator | None = None) -> None:
        self.auth = authenticator or Authenticator()
        self.allowed_uids = {0, os.getuid()}
        self._activity = threading.Event()

    def handle(self, request: dict) -> dict:
        op = request.get("op")
        try:
            if op == "token":
                token = self.auth.token(
                    _client_from(request),
                    interactive_allowed=bool(request.get("interactive", True)),
                    force_refresh=bool(request.get("force_refresh", False)),
                )
                return {"ok": True, "token": token.access_token, "account": token.account,
                        "expires_at": int(token.expires_at)}
            if op == "forget":
                self.auth.forget(_client_from(request) if "authority" in request else None)
                return {"ok": True}
            if op == "ping":
                return {"ok": True}
            return {"ok": False, "error": f"unknown op {op!r}"}
        except AuthError as error:
            return {"ok": False, "error": str(error)}

    def serve_connection(self, conn: socket.socket) -> None:
        with conn:
            try:
                uid = _peer_uid(conn)
                if uid not in self.allowed_uids:
                    log.warning("refusing request from uid %d", uid)
                    return
                reader = conn.makefile("rb")
                line = reader.readline(MAX_REQUEST)
                if not line:
                    return
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("request must be an object")
                log.info("%s request from uid %d", request.get("op"), uid)
                response = self.handle(request)
                if not response.get("ok"):
                    log.warning("request failed: %s", response.get("error"))
                conn.sendall(json.dumps(response).encode() + b"\n")
            except (OSError, ValueError) as error:
                log.warning("bad request: %s", error)
            finally:
                self._activity.set()

    def serve(self, listener: socket.socket) -> None:
        listener.settimeout(IDLE_EXIT_SECONDS)
        while True:
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                log.info("idle, exiting")
                return
            conn.settimeout(None)
            threading.Thread(target=self.serve_connection, args=(conn,), daemon=True).start()


def _listener() -> socket.socket:
    if os.environ.get("LISTEN_PID") == str(os.getpid()) and int(os.environ.get("LISTEN_FDS", "0")) >= 1:
        return socket.socket(fileno=SD_LISTEN_FDS_START)
    path = socket_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        listener.bind(path)
    finally:
        os.umask(old)
    listener.listen(8)
    return listener


def request(payload: dict, uid: int | None = None, timeout: float = 330) -> dict:
    runtime_dir = f"/run/user/{uid}" if uid is not None else None
    path = socket_path(runtime_dir)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        try:
            conn.connect(path)
        except OSError as error:
            raise AuthError(
                f"the sign-in agent is not reachable at {path} ({error.strerror}); "
                "is the user logged in with nm-openp2s-agent.socket enabled?"
            ) from None
        conn.sendall(json.dumps(payload).encode() + b"\n")
        line = conn.makefile("rb").readline(MAX_REQUEST)
    if not line:
        raise AuthError("the sign-in agent closed the connection without answering")
    return json.loads(line)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    Agent().serve(_listener())
    return 0
