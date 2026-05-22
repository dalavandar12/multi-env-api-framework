"""URL guardrail + content fetcher.

Heuristic-only safety checks (no external API). Exits non-zero on rejection
with a single line prefixed `[guardrail]`. On success, prints fetched text
to stdout for the calling script to consume.
"""
import ipaddress
import logging
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
import yaml

LOG = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "url_guardrail.yaml"


def _load_config() -> dict[str, Any]:
    with open(_CONFIG_PATH) as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return data


def _fail(reason: str) -> None:
    print(f"[guardrail] URL rejected: {reason}. See config/url_guardrail.yaml to adjust.")
    sys.exit(2)


def _check_scheme(url: str, cfg: dict[str, Any]) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in cfg["allowed_schemes"]:
        _fail(f"scheme '{parsed.scheme}' not in {cfg['allowed_schemes']}")
    if not parsed.hostname:
        _fail("URL missing hostname")
    return str(parsed.hostname)


def _check_ip(host: str, cfg: dict[str, Any]) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        _fail(f"DNS resolution failed: {exc}")
        return
    blocked = [ipaddress.ip_network(n) for n in cfg["blocked_ip_networks"]]
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])
        except ValueError:
            continue
        for net in blocked:
            if ip.version == net.version and ip in net:
                _fail(f"host resolves to blocked network {net} (ip={ip})")


def _check_tld(host: str, cfg: dict[str, Any]) -> None:
    tld = host.rsplit(".", 1)[-1].lower()
    if tld in {t.lower() for t in cfg["blocked_tlds"]}:
        _fail(f"TLD '.{tld}' is in blocklist")


def _check_robots(url: str, cfg: dict[str, Any]) -> None:
    if not cfg.get("respect_robots_txt", True):
        return
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
    except Exception as exc:
        LOG.info("robots.txt fetch failed (%s) — allowing", exc)
        return
    if not rp.can_fetch("*", url):
        _fail(f"robots.txt disallows {url}")


def _stream_fetch(url: str, cfg: dict[str, Any]) -> tuple[str, bytes]:
    timeout = cfg["request_timeout_seconds"]
    max_bytes = cfg["max_bytes"]
    max_redirects = cfg["max_redirects"]

    session = requests.Session()
    session.max_redirects = max_redirects
    try:
        resp = session.get(url, stream=True, timeout=timeout, allow_redirects=True)
    except requests.TooManyRedirects:
        _fail(f"more than {max_redirects} redirects")
        return ("", b"")
    except requests.RequestException as exc:
        _fail(f"request failed: {exc}")
        return ("", b"")

    for hop in resp.history:
        host = urlparse(hop.url).hostname or ""
        _check_ip(host, cfg)
        _check_tld(host, cfg)

    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if ctype not in cfg["allowed_content_types"]:
        _fail(f"Content-Type '{ctype}' not in allowlist")

    body = bytearray()
    for chunk in resp.iter_content(chunk_size=65536):
        body.extend(chunk)
        if len(body) > max_bytes:
            _fail(f"response exceeded {max_bytes} bytes")
    return ctype, bytes(body)


def fetch(url: str) -> tuple[str, bytes]:
    """Run guardrail and return (content_type, body) on success."""
    cfg = _load_config()
    host = _check_scheme(url, cfg)
    _check_ip(host, cfg)
    _check_tld(host, cfg)
    _check_robots(url, cfg)
    return _stream_fetch(url, cfg)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: fetch_url.py <https-url>", file=sys.stderr)
        sys.exit(64)
    ctype, body = fetch(sys.argv[1])
    sys.stdout.buffer.write(f"Content-Type: {ctype}\n\n".encode())
    sys.stdout.buffer.write(body)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
