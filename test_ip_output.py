"""Fetch /api/data and print a readable IPv4 summary.

Auth modes:
1) Signed mode (recommended):
   - --client-id / CF_CLIENT_ID
   - --client-secret / CF_CLIENT_SECRET
   - optional --hwid / CF_HWID
2) Admin fallback mode:
   - --key / CF_AUTH_KEY
"""

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import platform
import re
import secrets
import sys
import time
import uuid
from urllib.parse import urlparse

import requests


IPV4_REGEX = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
DEFAULT_URL = "https://cloudflareip.ocisg.xyz/api/data"


def is_valid_ipv4(value):
    try:
        ip = ipaddress.ip_address(value)
        return ip.version == 4
    except ValueError:
        return False


def unique_ipv4(values):
    result = []
    seen = set()
    for value in values:
        if is_valid_ipv4(value) and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def extract_from_source_item(item):
    """Extract IPv4 list from known payload variants."""
    if not isinstance(item, dict):
        return []

    ips = item.get("ips")
    if isinstance(ips, list):
        return unique_ipv4(ips)

    text = item.get("text")
    if isinstance(text, str):
        return unique_ipv4(IPV4_REGEX.findall(text))

    merged = []
    has_list = False
    for value in item.values():
        if isinstance(value, list):
            has_list = True
            merged.extend(value)
    if has_list:
        return unique_ipv4(merged)

    return []


def parse_api_error(resp):
    try:
        payload = resp.json()
    except json.JSONDecodeError:
        text = (resp.text or "").strip()
        return text[:200] if text else resp.reason

    if isinstance(payload, dict):
        if isinstance(payload.get("error"), str):
            return payload["error"]
        if isinstance(payload.get("message"), str):
            return payload["message"]
    return json.dumps(payload, ensure_ascii=False)[:200]


def default_hwid():
    seed = "|".join(
        [
            platform.system(),
            platform.machine(),
            platform.node(),
            str(uuid.getnode()),
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"hwid-{digest[:24]}"


def build_signed_headers(url, client_id, client_secret, hwid):
    ts = str(int(time.time()))
    nonce = secrets.token_urlsafe(18)
    path = urlparse(url).path or "/"
    canonical = f"GET\n{path}\n{ts}\n{nonce}\n{hwid}"
    token = hmac.new(
        client_secret.encode("utf-8"),
        canonical.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    headers = {
        "x-client-id": client_id,
        "x-hwid": hwid,
        "x-ts": ts,
        "x-nonce": nonce,
        "x-token": token,
    }
    return headers


def build_headers(url, args):
    hwid = args.hwid or default_hwid()
    if args.key:
        return {"x-auth-key": args.key, "x-hwid": hwid}, "admin-key", hwid

    if not args.client_id or not args.client_secret:
        print("Signed auth requires --client-id and --client-secret (or CF_CLIENT_ID/CF_CLIENT_SECRET).")
        sys.exit(2)

    headers = build_signed_headers(url, args.client_id, args.client_secret, hwid)
    return headers, "signed-v1", hwid


def fetch_ip_data(url, headers, timeout=12):
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        print(f"Request failed: {exc}")
        sys.exit(1)

    if not resp.ok:
        error_text = parse_api_error(resp)
        print(f"Request failed ({resp.status_code}): {error_text}")
        sys.exit(1)

    try:
        return resp.json(), resp.headers
    except json.JSONDecodeError as exc:
        print(f"Response is not valid JSON: {exc}")
        sys.exit(1)


def output_ips(payload, show_per_source=10):
    data = payload.get("data")
    if not isinstance(data, dict):
        print("Unexpected payload: missing or invalid 'data' field")
        return

    print("=== Cloudflare IP Summary ===")
    print(f"Timestamp: {payload.get('timestamp', 'unknown')}")
    meta = payload.get("meta")
    if isinstance(meta, dict):
        print(
            "Meta: "
            f"sources_total={meta.get('sources_total', '-')}, "
            f"sources_ok={meta.get('sources_ok', '-')}, "
            f"global_unique_ip_count={meta.get('global_unique_ip_count', '-')}"
        )
    print()

    all_ips = set()
    for source, item in data.items():
        ips = extract_from_source_item(item)
        all_ips.update(ips)
        print(f"[{source}] extracted {len(ips)} IPv4")
        for ip in ips[:show_per_source]:
            print(f"  {ip}")
        if len(ips) > show_per_source:
            print(f"  ... {len(ips) - show_per_source} more")
        print()

    print(f"Total unique IPv4 count: {len(all_ips)}")
    print("=== End ===")


def main():
    parser = argparse.ArgumentParser(description="Fetch /api/data and extract IPv4")
    parser.add_argument("--url", default=DEFAULT_URL, help="API endpoint URL")
    parser.add_argument("--client-id", default=os.getenv("CF_CLIENT_ID"), help="Signed auth client id")
    parser.add_argument("--client-secret", default=os.getenv("CF_CLIENT_SECRET"), help="Signed auth secret")
    parser.add_argument("--key", default=os.getenv("CF_AUTH_KEY"), help="Admin auth key fallback")
    parser.add_argument("--hwid", default=os.getenv("CF_HWID"), help="Hardware fingerprint")
    parser.add_argument("--timeout", type=int, default=12, help="Request timeout in seconds")
    parser.add_argument("--show-per-source", type=int, default=10, help="Max IPs to print for each source")
    args = parser.parse_args()

    headers, auth_mode, hwid = build_headers(args.url, args)
    print(f"Fetching IP data from {args.url}")
    print(f"Auth mode: {auth_mode}")
    print(f"Using hwid: {hwid}")

    payload, response_headers = fetch_ip_data(args.url, headers=headers, timeout=args.timeout)
    print(
        "Server auth/cache headers: "
        f"X-Auth-Mode={response_headers.get('X-Auth-Mode', '-')}, "
        f"X-Cache={response_headers.get('X-Cache', '-')}, "
        f"X-Role={response_headers.get('X-Role', '-')}"
    )
    output_ips(payload, show_per_source=max(1, args.show_per_source))


if __name__ == "__main__":
    main()
