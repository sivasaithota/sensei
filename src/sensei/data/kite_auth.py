"""Local Kite login. Credentials stay in macOS Keychain, never command arguments."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import re
import secrets
import subprocess
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

ACCOUNT = "sensei"
FIELDS = {"api-key", "api-secret", "access-token"}


class KiteAuthError(RuntimeError):
    pass


def _credential(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]{8,512}", value):
        raise KiteAuthError("Invalid credential format; enter only the credential value")
    return value


def read_secret(field: str) -> str | None:
    if field not in FIELDS:
        raise KiteAuthError("Unknown credential field")
    result = subprocess.run(["/usr/bin/security", "find-generic-password", "-a", ACCOUNT,
        "-s", f"sensei-kite-{field}", "-w"], capture_output=True, text=True)
    if result.returncode:
        return None
    return _credential(result.stdout.strip())


def write_secret(field: str, value: str) -> None:
    if field not in FIELDS:
        raise KiteAuthError("Unknown credential field")
    value = _credential(value)
    # Interactive security accepts commands through stdin. The secret is absent
    # from process arguments, environment variables and shell history.
    command = f"add-generic-password -U -a {ACCOUNT} -s sensei-kite-{field} -w {value}\n"
    result = subprocess.run(["/usr/bin/security", "-i"], input=command,
        capture_output=True, text=True)
    if result.returncode or read_secret(field) != value:
        raise KiteAuthError("Could not save credential in macOS Keychain")


def configure() -> None:
    for field in ("api-key", "api-secret"):
        value = getpass.getpass(f"Kite {field} (hidden; Enter keeps saved value): ").strip()
        if value:
            write_secret(field, value)
        elif read_secret(field) is None:
            raise KiteAuthError(f"No saved {field}; run configure again")
    print("Kite API key and secret saved in macOS Keychain. No login performed.")


def callback_token(path: str, expected_state: str) -> str | None:
    parsed = urlsplit(path)
    query = parse_qs(parsed.query)
    if parsed.path != "/" or query.get("status") != ["success"]:
        return None
    states, tokens = query.get("state", []), query.get("request_token", [])
    if len(states) != 1 or len(tokens) != 1 or not hmac.compare_digest(states[0], expected_state):
        return None
    try:
        return _credential(tokens[0])
    except KiteAuthError:
        return None


def exchange_token(api_key: str, api_secret: str, request_token: str, *, http=None) -> str:
    checksum = hashlib.sha256((api_key + request_token + api_secret).encode()).hexdigest()
    client = http or httpx.Client(timeout=30, follow_redirects=False)
    try:
        response = client.post("https://api.kite.trade/session/token",
            headers={"X-Kite-Version": "3"},
            data={"api_key": api_key, "request_token": request_token, "checksum": checksum})
        if response.status_code != 200:
            raise KiteAuthError(f"Kite login exchange failed (HTTP {response.status_code}); login again")
        body = response.json()
        if body.get("status") != "success" or body.get("data", {}).get("api_key") != api_key:
            raise KiteAuthError("Kite login response did not match the requested app")
        return _credential(body["data"]["access_token"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        raise KiteAuthError("Kite login exchange failed; no credentials were logged") from None
    finally:
        if http is None:
            client.close()


def login() -> None:
    api_key, api_secret = read_secret("api-key"), read_secret("api-secret")
    if not api_key or not api_secret:
        raise KiteAuthError("Run configure first to save the API key and secret")
    state = secrets.token_urlsafe(32)
    received = []

    class Callback(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *_args):
            pass  # Default HTTP logging would expose the request token.

        def do_GET(self):
            token = callback_token(self.path, state)
            valid_host = self.headers.get("Host") == "127.0.0.1:8000"
            ok = token is not None and valid_host
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(b"Login received. Return to your terminal." if ok else b"Invalid login callback.")
            if ok:
                received.append(token)

    with HTTPServer(("127.0.0.1", 8000), Callback) as server:
        server.timeout = 1
        server.socket.settimeout(1)
        url = "https://kite.zerodha.com/connect/login?" + urlencode({"v": "3", "api_key": api_key,
            "redirect_params": urlencode({"state": state})})
        print("Opening Kite login. Complete login in your browser within five minutes.", flush=True)
        if not webbrowser.open(url):
            raise KiteAuthError("Could not open the browser; use a local desktop terminal")
        deadline = time.monotonic() + 300
        while not received and time.monotonic() < deadline:
            server.handle_request()
    if not received:
        raise KiteAuthError("Login timed out; check app redirect is http://127.0.0.1:8000")
    write_secret("access-token", exchange_token(api_key, api_secret, received[0]))
    print("Kite access token saved in macOS Keychain. Data download can now start.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("configure", "login", "status"))
    args = parser.parse_args()
    try:
        if args.command == "configure":
            configure()
        elif args.command == "login":
            login()
        else:
            print(json.dumps({field: read_secret(field) is not None for field in sorted(FIELDS)}))
    except (KiteAuthError, OSError, EOFError):
        # OS/network exception text is deliberately not printed; it can carry
        # request details. Domain messages contain no submitted values.
        print("Kite setup did not finish. Check Keychain access, saved credentials and local port 8000.")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
