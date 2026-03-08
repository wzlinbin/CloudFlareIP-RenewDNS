#!/usr/bin/env python3
import argparse
import csv
import os
import re
import subprocess
import sys
from typing import List, Optional, Tuple

import requests

DEFAULT_IP_API_URL = "https://cloudflareip.ocisg.xyz/api/data"
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone CFIP runner for OpenWrt LuCI")
    parser.add_argument("--run-mode", choices=["dns_update", "speed_only"], default="dns_update")
    parser.add_argument("--source-mode", choices=["official", "custom"], default="official")
    parser.add_argument("--ip-api-url", default=DEFAULT_IP_API_URL)
    parser.add_argument("--custom-ip-api-url", default="")
    parser.add_argument("--cf-api-token", default="")
    parser.add_argument("--cf-zone-id", default="")
    parser.add_argument("--cf-dns-name", default="")
    parser.add_argument("--max-ips", type=int, default=200)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--cfst-path", default="/usr/bin/CloudflareST")
    parser.add_argument("--work-dir", default="/tmp/cfip-lite")
    return parser.parse_args()


def _safe_int(value: int, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed >= minimum else default


def _is_valid_ipv4(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except Exception:
        return False


def fetch_ip_pool(source_url: str, timeout: int, ip_file: str) -> List[str]:
    log(f"fetch ip list: {source_url}")
    resp = requests.get(source_url, timeout=timeout)
    resp.raise_for_status()

    ips: List[str] = []
    try:
        payload = resp.json()
        unique_ips = payload.get("global", {}).get("unique_ips", [])
        if isinstance(unique_ips, list):
            ips.extend(str(item).strip() for item in unique_ips if str(item).strip())
    except Exception:
        pass

    if not ips:
        ips.extend(IPV4_PATTERN.findall(resp.text or ""))

    deduped = sorted({ip for ip in ips if _is_valid_ipv4(ip)})
    if not deduped:
        raise RuntimeError("no valid IPv4 from source")

    with open(ip_file, "w", encoding="utf-8") as f:
        for ip in deduped:
            f.write(f"{ip}\n")
    log(f"ip count: {len(deduped)}")
    return deduped


def _read_csv_first_row(result_file: str) -> Optional[dict]:
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(result_file, "r", encoding=enc) as f:
                reader = csv.DictReader(f)
                return next(reader, None)
        except Exception:
            continue
    return None


def _pick_key(row: dict, patterns: List[str], fallback: str) -> str:
    for key in row.keys():
        low = str(key).lower()
        if all(p in low for p in patterns):
            return key
    return fallback


def run_speed_test(cfst_path: str, ip_file: str, result_file: str, max_ips: int, top_n: int) -> Tuple[str, str, str, float]:
    if not os.path.isfile(cfst_path):
        raise RuntimeError(f"CloudflareST not found: {cfst_path}")

    cmd = [
        cfst_path,
        "-f",
        ip_file,
        "-o",
        result_file,
        "-n",
        str(max_ips),
        "-dn",
        str(top_n),
    ]
    log("run CloudflareST...")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"CloudflareST failed (code={proc.returncode}): {err[:300]}")

    row = _read_csv_first_row(result_file)
    if not row:
        raise RuntimeError("result.csv is empty")

    ip_key = _pick_key(row, ["ip"], "IP")
    speed_key = _pick_key(row, ["mb/s"], "download")
    region_key = _pick_key(row, ["地区"], "region")
    if region_key not in row:
        region_key = _pick_key(row, ["region"], "region")

    best_ip = str(row.get(ip_key, "")).strip()
    speed_text = str(row.get(speed_key, "")).strip()
    region = str(row.get(region_key, "unknown")).strip() or "unknown"
    if not best_ip:
        raise RuntimeError("cannot parse best ip from result.csv")

    m = re.search(r"(\d+(?:\.\d+)?)", speed_text)
    speed_val = float(m.group(1)) if m else 0.0
    return best_ip, speed_text, region, speed_val


def update_cloudflare_dns(token: str, zone_id: str, dns_name: str, ip: str, timeout: int) -> str:
    if not token or not zone_id or not dns_name:
        raise RuntimeError("missing Cloudflare credentials")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    list_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    r = requests.get(list_url, headers=headers, params={"type": "A", "name": dns_name}, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    if not body.get("success", False):
        raise RuntimeError(f"Cloudflare query failed: {body}")

    records = body.get("result", [])
    if not records:
        raise RuntimeError(f"A record not found: {dns_name}")

    record = records[0]
    record_id = record.get("id")
    current_ip = record.get("content", "")
    proxied = bool(record.get("proxied", False))
    ttl = record.get("ttl", 60)

    if current_ip == ip:
        return "NO_CHANGE"

    update_url = f"{list_url}/{record_id}"
    payload = {
        "type": "A",
        "name": dns_name,
        "content": ip,
        "ttl": ttl if isinstance(ttl, int) and ttl > 0 else 60,
        "proxied": proxied,
    }
    u = requests.put(update_url, headers=headers, json=payload, timeout=timeout)
    u.raise_for_status()
    result = u.json()
    if not result.get("success", False):
        raise RuntimeError(f"Cloudflare update failed: {result}")
    return "UPDATED"


def main() -> int:
    args = parse_args()
    timeout = _safe_int(args.timeout, 15, 1)
    max_retries = _safe_int(args.max_retries, 3, 1)
    max_ips = _safe_int(args.max_ips, 200, 1)
    top_n = _safe_int(args.top_n, 10, 1)

    source_url = args.ip_api_url.strip() or DEFAULT_IP_API_URL
    if args.source_mode == "custom":
        source_url = args.custom_ip_api_url.strip()
        if not source_url:
            log("error: custom source mode requires custom ip api url")
            return 2

    if args.run_mode == "dns_update":
        if not args.cf_api_token.strip() or not args.cf_zone_id.strip() or not args.cf_dns_name.strip():
            log("error: dns_update mode requires Cloudflare token/zone/name")
            return 2

    work_dir = args.work_dir.strip() or "/tmp/cfip-lite"
    os.makedirs(work_dir, exist_ok=True)
    ip_file = os.path.join(work_dir, "ip.txt")
    result_file = os.path.join(work_dir, "result.csv")

    try:
        fetch_ip_pool(source_url, timeout, ip_file)
    except Exception as exc:
        log(f"error: fetch ip list failed: {exc}")
        return 3

    best_ip = ""
    speed_text = ""
    region = ""
    speed_val = 0.0
    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            log(f"retry {attempt}/{max_retries}")
        try:
            best_ip, speed_text, region, speed_val = run_speed_test(
                args.cfst_path.strip(),
                ip_file,
                result_file,
                max_ips,
                top_n,
            )
        except Exception as exc:
            log(f"error: speed test failed: {exc}")
            continue

        if best_ip and speed_val > 0:
            break

    if not best_ip or speed_val <= 0:
        log("error: no valid speed result")
        return 4

    log(f"best ip: {best_ip} | region: {region} | speed: {speed_text} MB/s")

    if args.run_mode == "speed_only":
        return 0

    try:
        status = update_cloudflare_dns(
            args.cf_api_token.strip(),
            args.cf_zone_id.strip(),
            args.cf_dns_name.strip(),
            best_ip,
            timeout,
        )
        if status == "NO_CHANGE":
            log("dns status: no change")
        else:
            log("dns status: updated")
        return 0
    except Exception as exc:
        log(f"error: dns update failed: {exc}")
        return 5


if __name__ == "__main__":
    sys.exit(main())

