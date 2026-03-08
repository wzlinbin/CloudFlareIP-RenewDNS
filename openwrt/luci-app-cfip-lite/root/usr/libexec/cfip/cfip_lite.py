#!/usr/bin/env python3
import argparse
import csv
import hashlib
import hmac
from html import escape as html_escape
import os
import platform
import re
import secrets
import subprocess
import sys
import time
import uuid
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

DEFAULT_IP_API_URL = "https://cloudflareip.ocisg.xyz/api/data"
DEFAULT_WORKER_BASE_URL = "https://cloudflareip.ocisg.xyz"
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def log(msg: str) -> None:
    print(msg, flush=True)


class IPFetchFailed(RuntimeError):
    def __init__(self, message: str, auth_mode: str = "unknown"):
        super().__init__(message)
        self.auth_mode = auth_mode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone CFIP runner for OpenWrt LuCI")
    parser.add_argument("--run-mode", choices=["dns_update", "speed_only"], default="dns_update")
    parser.add_argument("--source-mode", choices=["official", "custom"], default="official")
    parser.add_argument("--ip-api-url", default=DEFAULT_IP_API_URL)
    parser.add_argument("--custom-ip-api-url", default="")
    parser.add_argument("--auth-key", default="")
    parser.add_argument("--auth-client-id", default="")
    parser.add_argument("--auth-client-secret", default="")
    parser.add_argument("--auth-hwid", default="")
    parser.add_argument("--auto-register-once", default="1")
    parser.add_argument("--invite-code", default="")
    parser.add_argument("--auth-ephemeral-ttl-sec", type=int, default=180)
    parser.add_argument("--cf-api-token", default="")
    parser.add_argument("--cf-zone-id", default="")
    parser.add_argument("--cf-dns-name", default="")
    parser.add_argument("--tg-enabled", default="0")
    parser.add_argument("--tg-bot-token", default="")
    parser.add_argument("--tg-chat-id", default="")
    parser.add_argument("--tg-proxy-base-url", default=DEFAULT_WORKER_BASE_URL)
    parser.add_argument("--tg-auth-key", default="")
    parser.add_argument("--tg-disable-preview", default="1")
    parser.add_argument("--tg-timeout", type=int, default=10)
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


def _as_bool(value: str, default: bool = True) -> bool:
    raw = str(value or "").strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _is_valid_ipv4(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except Exception:
        return False


def _parse_tg_chat_ids(raw_value: str) -> List[str]:
    return [c.strip() for c in re.split(r"[, \n\r\t]+", str(raw_value or "").strip()) if c.strip()]


def _send_telegram_message(
    proxy_base_url: str,
    auth_key: str,
    token: str,
    chat_id: str,
    text: str,
    disable_preview: bool = True,
    timeout: int = 10,
) -> Tuple[bool, str]:
    if not token:
        return False, "bot token is empty"
    if not chat_id:
        return False, "chat id is empty"

    base = str(proxy_base_url or "").strip().rstrip("/")
    parsed = urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        base = DEFAULT_WORKER_BASE_URL
    url = f"{base}/tg/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview,
    }
    headers = {}
    if auth_key:
        headers["x-auth-key"] = auth_key
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except Exception as exc:
        return False, str(exc)

    try:
        body = resp.json()
    except Exception:
        body = {}

    if resp.status_code == 200 and (not isinstance(body, dict) or body.get("ok") is not False):
        return True, ""

    if isinstance(body, dict):
        desc = str(body.get("description", "")).strip()
        if desc:
            return False, desc
    return False, f"http {resp.status_code}"


def push_telegram_notification(args: argparse.Namespace, text: str) -> None:
    if not _as_bool(args.tg_enabled, False):
        return

    token = str(args.tg_bot_token or "").strip()
    chat_ids = _parse_tg_chat_ids(args.tg_chat_id)
    if not token or not chat_ids:
        log("tg push skipped: token or chat id missing")
        return

    proxy_base_url = str(args.tg_proxy_base_url or "").strip() or DEFAULT_WORKER_BASE_URL
    tg_auth_key = str(args.tg_auth_key or "").strip() or str(args.auth_key or "").strip()
    disable_preview = _as_bool(args.tg_disable_preview, True)
    tg_timeout = _safe_int(args.tg_timeout, 10, 1)
    for cid in chat_ids:
        ok, reason = _send_telegram_message(
            proxy_base_url=proxy_base_url,
            auth_key=tg_auth_key,
            token=token,
            chat_id=cid,
            text=text,
            disable_preview=disable_preview,
            timeout=tg_timeout,
        )
        if ok:
            log(f"tg push ok: {cid}")
        else:
            log(f"tg push failed: {cid} ({reason})")


def _default_hwid() -> str:
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


def _build_signed_headers(url: str, method: str, client_id: str, client_secret: str, hwid: str) -> Dict[str, str]:
    ts = str(int(time.time()))
    nonce = secrets.token_urlsafe(18)
    path = urlparse(url).path or "/"
    canonical = f"{method.upper()}\n{path}\n{ts}\n{nonce}\n{hwid}"
    token = hmac.new(client_secret.encode("utf-8"), canonical.encode("utf-8"), digestmod=hashlib.sha256).hexdigest()
    return {
        "x-client-id": client_id,
        "x-hwid": hwid,
        "x-ts": ts,
        "x-nonce": nonce,
        "x-token": token,
    }


def _resolve_register_once_url(source_url: str) -> Optional[str]:
    parsed = urlparse(source_url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/api/register-once"


def _auto_register_ephemeral_client(
    source_url: str,
    timeout: int,
    auth_key: str,
    invite_code: str,
    auth_hwid: str,
    ttl_sec: int,
) -> Optional[Dict[str, str]]:
    register_url = _resolve_register_once_url(source_url)
    if not register_url:
        return None

    hwid = auth_hwid or _default_hwid()
    ttl = _safe_int(ttl_sec, 180, minimum=30)
    ttl = min(ttl, 1800)
    client_id = f"auto-{int(time.time())}-{secrets.token_hex(6)}"
    client_secret = secrets.token_hex(32)

    payload = {
        "client_id": client_id,
        "secret": client_secret,
        "hwid": hwid,
        "role": "user",
        "one_time": True,
        "ttl_sec": ttl,
    }
    if invite_code:
        payload["invite_code"] = invite_code

    headers = {"Content-Type": "application/json"}
    if auth_key:
        headers["x-auth-key"] = auth_key

    try:
        resp = requests.post(register_url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
        if not isinstance(body, dict) or body.get("ok") is not True:
            log(f"warn: auto register returned unexpected payload: {register_url}")
            return None
        return {
            "client_id": str(body.get("client_id") or client_id).strip(),
            "client_secret": str(body.get("secret") or client_secret).strip(),
            "hwid": hwid,
        }
    except Exception as exc:
        log(f"warn: auto register once failed: {exc}")
        return None


def _build_ip_api_header_candidates(
    source_mode: str,
    source_url: str,
    custom_url: str,
    timeout: int,
    auth_key: str,
    auth_client_id: str,
    auth_client_secret: str,
    auth_hwid: str,
    auto_register_once: bool,
    invite_code: str,
    auth_ephemeral_ttl_sec: int,
) -> List[Tuple[Dict[str, str], str]]:
    if source_mode == "custom":
        return [({}, "none-custom")]
    if custom_url and source_url.rstrip("/") == custom_url.rstrip("/"):
        return [({}, "none-custom")]

    candidates: List[Tuple[Dict[str, str], str]] = []

    if auth_client_id and auth_client_secret:
        hwid = auth_hwid or _default_hwid()
        candidates.append(
            (
                _build_signed_headers(source_url, "GET", auth_client_id, auth_client_secret, hwid),
                "signed-v1",
            )
        )

    if auto_register_once:
        ephemeral = _auto_register_ephemeral_client(
            source_url=source_url,
            timeout=timeout,
            auth_key=auth_key,
            invite_code=invite_code,
            auth_hwid=auth_hwid,
            ttl_sec=auth_ephemeral_ttl_sec,
        )
        if ephemeral:
            candidates.append(
                (
                    _build_signed_headers(
                        source_url,
                        "GET",
                        ephemeral["client_id"],
                        ephemeral["client_secret"],
                        ephemeral["hwid"],
                    ),
                    "signed-auto-once",
                )
            )

    if auth_key:
        candidates.append(({"x-auth-key": auth_key}, "admin-key"))

    candidates.append(({}, "none"))
    return candidates


def fetch_ip_pool(source_url: str, timeout: int, ip_file: str, headers: Dict[str, str], auth_mode: str) -> List[str]:
    log("fetch ip list...")
    log(f"ip source auth mode: {auth_mode}")
    resp = requests.get(source_url, headers=headers, timeout=timeout)
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


def fetch_ip_pool_with_fallback(
    source_url: str,
    timeout: int,
    ip_file: str,
    candidates: List[Tuple[Dict[str, str], str]],
) -> Tuple[List[str], str]:
    last_error: Optional[Exception] = None
    last_mode = "unknown"
    for headers, auth_mode in candidates:
        try:
            ips = fetch_ip_pool(source_url, timeout, ip_file, headers, auth_mode)
            return ips, auth_mode
        except Exception as exc:
            last_error = exc
            last_mode = auth_mode
            log(f"warn: ip source mode failed [{auth_mode}]: {exc}")
            continue

    raise IPFetchFailed(str(last_error) if last_error else "all auth modes failed", auth_mode=last_mode)


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
    custom_url = args.custom_ip_api_url.strip()
    if args.source_mode == "custom":
        source_url = custom_url
        if not source_url:
            log("error: custom source mode requires custom ip api url")
            push_telegram_notification(
                args,
                "❌ <b>CFIP 执行失败</b>\n<b>原因:</b> 自定义源模式未填写地址。",
            )
            return 2

    if args.run_mode == "dns_update":
        if not args.cf_api_token.strip() or not args.cf_zone_id.strip() or not args.cf_dns_name.strip():
            log("error: dns_update mode requires Cloudflare token/zone/name")
            push_telegram_notification(
                args,
                "❌ <b>CFIP 执行失败</b>\n<b>原因:</b> DNS 更新模式缺少 Cloudflare 参数。",
            )
            return 2

    work_dir = args.work_dir.strip() or "/tmp/cfip-lite"
    os.makedirs(work_dir, exist_ok=True)
    ip_file = os.path.join(work_dir, "ip.txt")
    result_file = os.path.join(work_dir, "result.csv")

    candidates = _build_ip_api_header_candidates(
        source_mode=args.source_mode,
        source_url=source_url,
        custom_url=custom_url,
        timeout=timeout,
        auth_key=args.auth_key.strip(),
        auth_client_id=args.auth_client_id.strip(),
        auth_client_secret=args.auth_client_secret.strip(),
        auth_hwid=args.auth_hwid.strip(),
        auto_register_once=_as_bool(args.auto_register_once, True),
        invite_code=args.invite_code.strip(),
        auth_ephemeral_ttl_sec=_safe_int(args.auth_ephemeral_ttl_sec, 180, 30),
    )
    auth_mode = "unknown"

    try:
        _, auth_mode = fetch_ip_pool_with_fallback(source_url, timeout, ip_file, candidates)
    except Exception as exc:
        auth_mode = str(getattr(exc, "auth_mode", auth_mode))
        log(f"error: fetch ip list failed: {exc}")
        push_telegram_notification(
            args,
            (
                "❌ <b>CFIP 获取 IP 失败</b>\n"
                f"<b>来源:</b> <code>{html_escape(source_url)}</code>\n"
                f"<b>鉴权模式:</b> <code>{html_escape(auth_mode)}</code>\n"
                f"<b>错误:</b> <code>{html_escape(str(exc))}</code>"
            ),
        )
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
        push_telegram_notification(
            args,
            (
                "❌ <b>CFIP 测速失败</b>\n"
                f"<b>来源:</b> <code>{html_escape(source_url)}</code>\n"
                f"<b>鉴权模式:</b> <code>{html_escape(auth_mode)}</code>\n"
                "<b>原因:</b> 未获得有效测速结果。"
            ),
        )
        return 4

    log(f"best ip: {best_ip} | region: {region} | speed: {speed_text} MB/s")

    if args.run_mode == "speed_only":
        push_telegram_notification(
            args,
            (
                "✅ <b>CFIP 测速完成</b>\n"
                f"<b>推荐 IP:</b> <code>{html_escape(best_ip)}</code>\n"
                f"<b>地区:</b> <code>{html_escape(region)}</code>\n"
                f"<b>速度:</b> <b>{html_escape(speed_text)} MB/s</b>"
            ),
        )
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
            push_telegram_notification(
                args,
                (
                    "ℹ️ <b>CFIP DNS 无需更新</b>\n"
                    f"<b>域名:</b> <code>{html_escape(args.cf_dns_name.strip())}</code>\n"
                    f"<b>最优 IP:</b> <code>{html_escape(best_ip)}</code>\n"
                    f"<b>速度:</b> <b>{html_escape(speed_text)} MB/s</b>"
                ),
            )
        else:
            log("dns status: updated")
            push_telegram_notification(
                args,
                (
                    "✅ <b>CFIP DNS 更新成功</b>\n"
                    f"<b>域名:</b> <code>{html_escape(args.cf_dns_name.strip())}</code>\n"
                    f"<b>新 IP:</b> <code>{html_escape(best_ip)}</code>\n"
                    f"<b>地区:</b> <code>{html_escape(region)}</code>\n"
                    f"<b>速度:</b> <b>{html_escape(speed_text)} MB/s</b>"
                ),
            )
        return 0
    except Exception as exc:
        log(f"error: dns update failed: {exc}")
        push_telegram_notification(
            args,
            (
                "❌ <b>CFIP DNS 更新失败</b>\n"
                f"<b>域名:</b> <code>{html_escape(args.cf_dns_name.strip())}</code>\n"
                f"<b>最优 IP:</b> <code>{html_escape(best_ip)}</code>\n"
                f"<b>错误:</b> <code>{html_escape(str(exc))}</code>"
            ),
        )
        return 5


if __name__ == "__main__":
    sys.exit(main())
