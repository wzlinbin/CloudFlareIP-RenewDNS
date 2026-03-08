
import requests
import re
import os
import json
import copy
import subprocess
import csv
import sys
import hashlib
import hmac
import time
import secrets
import webbrowser
import platform
import uuid
import base64
import datetime
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, quote
from concurrent.futures import ThreadPoolExecutor, as_completed

# Windows 终端强制 UTF-8 输出，避免 emoji / 中文字符编码错误
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def _exit_with_pause(code=1):
    """报错退出前暂停，防止窗口一闪而过"""
    if code == 0:
        _show_tks_page_content()
    print("\n按回车键退出...")
    try:
        input()
    except Exception:
        pass
    sys.exit(code)


def _safe_int(value, default, min_value=1):
    """将配置值安全转换为整数，非法值回退到默认值。"""
    try:
        parsed = int(value)

    except (TypeError, ValueError):
        return default
    if parsed < min_value:
        return default
    return parsed


def _brief_request_error(exc):
    if isinstance(exc, requests.exceptions.Timeout):
        return "请求超时"
    if isinstance(exc, requests.exceptions.SSLError):
        return "SSL连接失败"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "网络连接失败"
    if isinstance(exc, requests.exceptions.HTTPError):
        resp = getattr(exc, "response", None)
        if resp is not None and getattr(resp, "status_code", None):
            return f"HTTP {resp.status_code}"
        return "HTTP错误"
    return "请求失败"


DEFAULT_WORKER_BASE_URL = "https://cloudflareip.ocisg.xyz"
DEFAULT_IP_SOURCE_URL = f"{DEFAULT_WORKER_BASE_URL}/api/data"
TKS_PAGE_URL = f"{DEFAULT_WORKER_BASE_URL}/tks"
_TKS_SPONSOR_CACHE = None


def _strip_html_tags(value):
    text = re.sub(r"(?is)<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _fetch_tks_sponsor_text():
    global _TKS_SPONSOR_CACHE
    if _TKS_SPONSOR_CACHE is not None:
        return _TKS_SPONSOR_CACHE
    try:
        resp = requests.get(TKS_PAGE_URL, timeout=10)
        resp.raise_for_status()
        html = resp.text or ""
    except Exception:
        _TKS_SPONSOR_CACHE = ""
        return _TKS_SPONSOR_CACHE

    compact = re.sub(r"\s+", " ", html)
    m = re.search(r"项目赞助人员[：:]\s*(.*?)</p>", compact, flags=re.IGNORECASE)
    if m:
        _TKS_SPONSOR_CACHE = _strip_html_tags(m.group(1))
        return _TKS_SPONSOR_CACHE

    plain = _strip_html_tags(compact)
    m = re.search(r"项目赞助人员[：:]\s*([^。；;\n\r]+)", plain)
    _TKS_SPONSOR_CACHE = m.group(1).strip() if m else ""
    return _TKS_SPONSOR_CACHE


def _escape_html(value):
    text = str(value or "")
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))


def _append_ack_to_push_message(msg):
    sponsor_text = _fetch_tks_sponsor_text()
    sponsor_line = f"感谢本项目赞助人员：{sponsor_text}" if sponsor_text else "感谢本项目赞助人员：详见感谢页面"
    ack = (
        "\n\n"
        "<b>========致谢========</b>\n"
        "\n"
        "<b>本项目GitHub地址：</b>https://github.com/wzlinbin/CloudFlareIP-RenewDNS\n"
        "<b>感谢</b> https://github.com/XIU2/CloudflareSpeedTest 项目，提供了测速模块能力。\n"
        "\n"
        f"<b>{_escape_html(sponsor_line)}</b>\n"
        "<b>感谢页面：</b>https://cloudflareip.ocisg.xyz/tks\n"
        "<b>========================</b>"
    )
    return f"{msg}{ack}"


def _show_tks_page_content():
    sponsor_text = _fetch_tks_sponsor_text()
    print("\n========致谢========")
    print("本项目GitHub地址：https://github.com/wzlinbin/CloudFlareIP-RenewDNS")
    print("感谢 https://github.com/XIU2/CloudflareSpeedTest 项目，提供了测速模块能力。")
    print("如果这个软件对你有帮助，麻烦给个🌟，也可以点击下面链接请作者喝杯咖啡，并将您的赞助列入项目支持人员列表")
    if sponsor_text:
        print(f"感谢本项目赞助人员：{sponsor_text}")
    else:
        print("感谢本项目赞助人员：获取失败，请访问下方链接查看")
    print("感谢页面：https://cloudflareip.ocisg.xyz/tks")
    print("========================")
   

def _get_url_origin(url):
    if not isinstance(url, str):
        return ""
    raw = url.strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _get_official_ip_source_url(settings):
    url = settings.get("ip_api_url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    return DEFAULT_IP_SOURCE_URL


def _get_preferred_worker_base_url(config):
    settings = config.get("settings", {})
    custom_url = settings.get("custom_ip_api_url", "")
    custom_origin = _get_url_origin(custom_url)
    if custom_origin:
        return custom_origin
    return DEFAULT_WORKER_BASE_URL


def _get_config_path():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.json')
    if os.path.exists(config_path):
        return config_path
    return 'config.json'


def _build_default_config():
    return {
        "cloudflare": {},
        "dns": {
            "provider": "cloudflare",
            "dnspod": {
                "secret_id": "",
                "secret_key": "",
                "domain": "",
                "sub_domain": "@",
                "record_line": "默认",
                "ttl": 60,
            },
            "aliyun": {
                "access_key_id": "",
                "access_key_secret": "",
                "domain": "",
                "rr": "@",
                "ttl": 60,
                "endpoint": "https://alidns.aliyuncs.com/",
            },
            "route53": {
                "access_key_id": "",
                "secret_access_key": "",
                "session_token": "",
                "hosted_zone_id": "",
                "record_name": "",
                "ttl": 60,
            },
            "huawei": {
                "token": "",
                "zone_id": "",
                "record_name": "",
                "ttl": 60,
                "base_url": "https://dns.myhuaweicloud.com",
            },
            "gcp": {
                "access_token": "",
                "project_id": "",
                "managed_zone": "",
                "record_name": "",
                "ttl": 60,
            },
            "azure": {
                "access_token": "",
                "subscription_id": "",
                "resource_group": "",
                "zone_name": "",
                "record_name": "@",
                "ttl": 60,
                "api_version": "2018-05-01",
            },
        },
        "telegram": {
            "auth_key": "",
            "bot_token": "",
            "chat_id": "",
        },
        "settings": {
            "ip_api_url": DEFAULT_IP_SOURCE_URL,
            "max_ips": 200,
            "top_n": 10,
            "timeout": 15,
            "max_retries": 3,
            "auth_key": "",
            "auto_register_once": True,
            "auth_ephemeral_ttl_sec": 180,
            "invite_code": "",
            "custom_ip_api_url": "",
            "active_dns_profile_id": "",
        },
        "dns_profiles": [],
    }


def _default_hwid():
    seed = "|".join([
        platform.system(),
        platform.machine(),
        platform.node(),
        str(uuid.getnode()),
    ])
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"hwid-{digest[:24]}"


def _build_signed_worker_headers(url, method, client_id, client_secret, hwid):
    ts = str(int(time.time()))
    nonce = secrets.token_urlsafe(18)
    path = urlparse(url).path or "/"
    canonical = f"{method.upper()}\n{path}\n{ts}\n{nonce}\n{hwid}"
    token = hmac.new(
        client_secret.encode("utf-8"),
        canonical.encode("utf-8"),
        digestmod=hashlib.sha256
    ).hexdigest()
    return {
        "x-client-id": client_id,
        "x-hwid": hwid,
        "x-ts": ts,
        "x-nonce": nonce,
        "x-token": token,
    }


def _resolve_register_once_url(source_url):
    parsed = urlparse(source_url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/api/register-once"


def _get_admin_auth_key(config):
    settings = config.get("settings", {})
    return settings.get("auth_key") or config.get("telegram", {}).get("auth_key", "")


def _auto_register_ephemeral_client(config, source_url, timeout):
    register_url = _resolve_register_once_url(source_url)
    if not register_url:
        return None

    settings = config.get("settings", {})
    admin_key = _get_admin_auth_key(config)
    invite_code = (
        settings.get("invite_code")
        or settings.get("register_invite_code")
        or ""
    )
    hwid = settings.get("auth_hwid") or settings.get("hwid") or _default_hwid()
    ttl_sec = _safe_int(settings.get("auth_ephemeral_ttl_sec", 180), 180, min_value=30)
    ttl_sec = min(ttl_sec, 1800)

    client_id = f"auto-{int(time.time())}-{secrets.token_hex(6)}"
    client_secret = secrets.token_hex(32)
    payload = {
        "client_id": client_id,
        "secret": client_secret,
        "hwid": hwid,
        "role": "user",
        "one_time": True,
        "ttl_sec": ttl_sec
    }
    if invite_code:
        payload["invite_code"] = str(invite_code).strip()

    headers = {
        "Content-Type": "application/json"
    }
    if admin_key:
        headers["x-auth-key"] = admin_key

    try:
        resp = requests.post(register_url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
        if not isinstance(body, dict) or body.get("ok") is not True:
            print(f"警告: 自动注册返回异常。register={register_url}")
            return None
        return {
            "client_id": body.get("client_id") or client_id,
            "client_secret": body.get("secret") or client_secret,
            "hwid": hwid
        }
    except Exception as e:
        print(f"警告: 自动注册一次性凭据失败: {e}")
        return None


def _resolve_ip_source_urls(settings):
    runtime_urls = settings.get("_runtime_source_urls")
    if isinstance(runtime_urls, list):
        urls = [u.strip() for u in runtime_urls if isinstance(u, str) and u.strip()]
        if urls:
            return urls

    custom_url = settings.get("custom_ip_api_url")
    if isinstance(custom_url, str) and custom_url.strip():
        return [custom_url.strip()]

    urls = []
    ip_sources = settings.get("ip_sources")
    if isinstance(ip_sources, list):
        urls.extend([u.strip() for u in ip_sources if isinstance(u, str) and u.strip()])
    elif isinstance(ip_sources, str) and ip_sources.strip():
        urls.append(ip_sources.strip())

    urls.append(_get_official_ip_source_url(settings))

    if not urls:
        urls = [DEFAULT_IP_SOURCE_URL]

    deduped = []
    seen = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def _build_ip_api_headers(config, source_url, timeout):
    settings = config.get("settings", {})
    if settings.get("_runtime_custom_source_no_auth") is True:
        return {}, "none-custom"
    custom_url = str(settings.get("custom_ip_api_url", "")).strip()
    if custom_url and source_url.rstrip("/") == custom_url.rstrip("/"):
        return {}, "none-custom"

    client_id = (
        settings.get("auth_client_id")
        or settings.get("client_id")
        or config.get("telegram", {}).get("client_id")
        or ""
    )
    client_secret = (
        settings.get("auth_client_secret")
        or settings.get("client_secret")
        or config.get("telegram", {}).get("client_secret")
        or ""
    )

    if client_id and client_secret:
        hwid = settings.get("auth_hwid") or settings.get("hwid") or _default_hwid()
        return _build_signed_worker_headers(
            source_url,
            "GET",
            client_id=client_id,
            client_secret=client_secret,
            hwid=hwid
        ), "signed-v1"

    auto_register_once = settings.get("auto_register_once", True)
    if auto_register_once:
        ephemeral = _auto_register_ephemeral_client(config, source_url, timeout)
        if ephemeral:
            return _build_signed_worker_headers(
                source_url,
                "GET",
                client_id=ephemeral["client_id"],
                client_secret=ephemeral["client_secret"],
                hwid=ephemeral["hwid"]
            ), "signed-auto-once"

    auth_key = _get_admin_auth_key(config)
    if auth_key:
        return {"x-auth-key": auth_key}, "admin-key"
    return {}, "none"


# ============================================================
# 配置加载模块
# ============================================================
def load_config():
    """从 config.json 加载系统配置"""
    config_path = _get_config_path()
    if not os.path.exists(config_path):
        default_config = _build_default_config()
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        print(f"未检测到配置文件，已自动创建默认配置: {config_path}")
        return default_config
    with open(config_path, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def save_config(config):
    """将配置写回 config.json"""
    config_path = _get_config_path()
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def validate_ip_source_url(url, timeout=10):
    """检查自建 IP 源是否可访问（无鉴权）"""
    print(f"正在检查自建IP源可访问性: {url}")
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        body = (resp.text or "").strip()
        if not body:
            print("检查失败：接口返回为空。")
            return False
        print("检查通过：自建IP源可访问。")
        return True
    except Exception as e:
        print(f"检查失败：{e}")
        return False


def configure_custom_ip_source(config, allow_blank_use_existing=True, allow_back=False):
    """配置并验证自建 IP 源 URL，成功后写入配置文件。"""
    settings = config.setdefault('settings', {})
    current_url = str(settings.get("custom_ip_api_url", "")).strip()
    timeout = _safe_int(settings.get('timeout', 15), 15, min_value=1)

    while True:
        if current_url and allow_blank_use_existing:
            if allow_back:
                prompt = f"请输入自建优选IP源URL（回车使用当前：{current_url}，B=返回上层）: "
            else:
                prompt = f"请输入自建优选IP源URL（回车使用当前：{current_url}）: "
        else:
            prompt = "请输入自建优选IP源URL: "
            if allow_back:
                prompt = "请输入自建优选IP源URL（B=返回上层）: "
        input_url = input(prompt).strip()
        if allow_back and input_url.lower() == "b":
            return None
        if not input_url:
            if current_url and allow_blank_use_existing:
                input_url = current_url
            else:
                print("URL 不能为空。")
                continue

        if not (input_url.startswith("http://") or input_url.startswith("https://")):
            print("URL 无效，请输入以 http:// 或 https:// 开头的有效地址。")
            continue

        if not validate_ip_source_url(input_url, timeout=timeout):
            continue

        settings["custom_ip_api_url"] = input_url
        save_config(config)
        print(f"已保存自建优选IP源: {input_url}")
        return input_url


def _prompt_text(label, current_value="", allow_empty=False):
    while True:
        if current_value:
            text = input(f"{label}（当前: {current_value}，回车沿用）: ").strip()
            if not text:
                return current_value
            return text
        text = input(f"{label}: ").strip()
        if text:
            return text
        if allow_empty:
            return ""
        print("该项不能为空。")


def _prompt_int(label, current_value=None, default_value=60, min_value=1):
    display_default = default_value if current_value is None else current_value
    while True:
        text = input(f"{label}（当前/默认: {display_default}）: ").strip()
        if not text:
            try:
                value = int(display_default)
            except Exception:
                value = default_value
        else:
            try:
                value = int(text)
            except Exception:
                print("请输入整数。")
                continue
        if value < min_value:
            print(f"请输入不小于 {min_value} 的整数。")
            continue
        return value


def _dns_required_fields(provider):
    fields = {
        "cloudflare": ["api_token", "zone_id", "dns_name"],
        "dnspod": ["secret_id", "secret_key", "domain", "sub_domain"],
        "aliyun": ["access_key_id", "access_key_secret", "domain", "rr"],
        "route53": ["access_key_id", "secret_access_key", "hosted_zone_id", "record_name"],
        "huawei": ["token", "zone_id", "record_name"],
        "gcp": ["access_token", "project_id", "managed_zone", "record_name"],
        "azure": ["access_token", "subscription_id", "resource_group", "zone_name", "record_name"]
    }
    return fields.get(provider, [])


def _missing_dns_config_fields(config):
    provider = _get_dns_provider(config)
    if provider == "cloudflare":
        cfg = config.get("cloudflare", {})
    else:
        cfg = config.get("dns", {}).get(provider, {})
    missing = []
    for key in _dns_required_fields(provider):
        value = cfg.get(key)
        if value is None:
            missing.append(key)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(key)
    return missing


def _run_dns_provider_wizard(config, auto_save=True):
    dns_root = config.setdefault("dns", {})
    current_provider = _get_dns_provider(config)
    providers = [
        ("1", "cloudflare", "Cloudflare"),
        ("2", "dnspod", "DNSPod"),
        ("3", "aliyun", "阿里云DNS"),
        ("4", "route53", "AWS Route53"),
        ("5", "huawei", "华为云DNS"),
        ("6", "gcp", "Google Cloud DNS"),
        ("7", "azure", "Azure DNS"),
    ]
    current_no = next((no for no, code, _ in providers if code == current_provider), "1")

    print("\n请选择 DNS 解析供应商：")
    for no, _, name in providers:
        print(f"{no}. {name}")
    print("8. 返回")
    selected_no = input(f"> （默认 {current_no}）").strip() or current_no
    if selected_no == "8":
        print("已返回上一级。")
        return False
    selected = next((item for item in providers if item[0] == selected_no), None)
    if not selected:
        print("无效选择，保持当前供应商。")
        selected = next((item for item in providers if item[1] == current_provider), providers[0])

    provider = selected[1]
    provider_name = selected[2]
    dns_root["provider"] = provider
    print(f"\n开始配置 {provider_name} ...")

    if provider == "cloudflare":
        cf = config.setdefault("cloudflare", {})
        cf["api_token"] = _prompt_text("Cloudflare API Token", str(cf.get("api_token", "")).strip())
        cf["zone_id"] = _prompt_text("Cloudflare Zone ID", str(cf.get("zone_id", "")).strip())
        cf["dns_name"] = _prompt_text("需要更新的域名(dns_name)", str(cf.get("dns_name", "")).strip())
        if auto_save:
            save_config(config)
        return True

    provider_cfg = dns_root.setdefault(provider, {})
    if provider == "dnspod":
        provider_cfg["secret_id"] = _prompt_text("DNSPod SecretId", str(provider_cfg.get("secret_id", "")).strip())
        provider_cfg["secret_key"] = _prompt_text("DNSPod SecretKey", str(provider_cfg.get("secret_key", "")).strip())
        provider_cfg["domain"] = _prompt_text("主域名(domain)", str(provider_cfg.get("domain", "")).strip())
        provider_cfg["sub_domain"] = _prompt_text("主机记录(sub_domain, 如 @/www)", str(provider_cfg.get("sub_domain", "@")).strip())
        provider_cfg["record_line"] = _prompt_text("线路(record_line)", str(provider_cfg.get("record_line", "默认")).strip())
        provider_cfg["ttl"] = _prompt_int("TTL", provider_cfg.get("ttl", 60), default_value=60, min_value=1)
    elif provider == "aliyun":
        provider_cfg["access_key_id"] = _prompt_text("阿里云 AccessKeyId", str(provider_cfg.get("access_key_id", "")).strip())
        provider_cfg["access_key_secret"] = _prompt_text("阿里云 AccessKeySecret", str(provider_cfg.get("access_key_secret", "")).strip())
        provider_cfg["domain"] = _prompt_text("主域名(domain)", str(provider_cfg.get("domain", "")).strip())
        provider_cfg["rr"] = _prompt_text("主机记录(rr, 如 @/www)", str(provider_cfg.get("rr", "@")).strip())
        provider_cfg["ttl"] = _prompt_int("TTL", provider_cfg.get("ttl", 60), default_value=60, min_value=1)
        provider_cfg["endpoint"] = _prompt_text("阿里云 endpoint", str(provider_cfg.get("endpoint", "https://alidns.aliyuncs.com/")).strip())
    elif provider == "route53":
        provider_cfg["access_key_id"] = _prompt_text("AWS AccessKeyId", str(provider_cfg.get("access_key_id", "")).strip())
        provider_cfg["secret_access_key"] = _prompt_text("AWS SecretAccessKey", str(provider_cfg.get("secret_access_key", "")).strip())
        provider_cfg["session_token"] = _prompt_text("AWS SessionToken(可留空)", str(provider_cfg.get("session_token", "")).strip(), allow_empty=True)
        provider_cfg["hosted_zone_id"] = _prompt_text("HostedZoneId", str(provider_cfg.get("hosted_zone_id", "")).strip())
        provider_cfg["record_name"] = _prompt_text("记录名(record_name, 如 sub.example.com.)", str(provider_cfg.get("record_name", "")).strip())
        provider_cfg["ttl"] = _prompt_int("TTL", provider_cfg.get("ttl", 60), default_value=60, min_value=1)
    elif provider == "huawei":
        provider_cfg["token"] = _prompt_text("华为云 X-Auth-Token", str(provider_cfg.get("token", "")).strip())
        provider_cfg["zone_id"] = _prompt_text("华为云 Zone ID", str(provider_cfg.get("zone_id", "")).strip())
        provider_cfg["record_name"] = _prompt_text("记录名(record_name)", str(provider_cfg.get("record_name", "")).strip())
        provider_cfg["ttl"] = _prompt_int("TTL", provider_cfg.get("ttl", 60), default_value=60, min_value=1)
        provider_cfg["base_url"] = _prompt_text("华为云 DNS base_url", str(provider_cfg.get("base_url", "https://dns.myhuaweicloud.com")).strip())
    elif provider == "gcp":
        provider_cfg["access_token"] = _prompt_text("GCP Access Token", str(provider_cfg.get("access_token", "")).strip())
        provider_cfg["project_id"] = _prompt_text("GCP Project ID", str(provider_cfg.get("project_id", "")).strip())
        provider_cfg["managed_zone"] = _prompt_text("Managed Zone 名称", str(provider_cfg.get("managed_zone", "")).strip())
        provider_cfg["record_name"] = _prompt_text("记录名(record_name, 如 sub.example.com.)", str(provider_cfg.get("record_name", "")).strip())
        provider_cfg["ttl"] = _prompt_int("TTL", provider_cfg.get("ttl", 60), default_value=60, min_value=1)
    elif provider == "azure":
        provider_cfg["access_token"] = _prompt_text("Azure Access Token", str(provider_cfg.get("access_token", "")).strip())
        provider_cfg["subscription_id"] = _prompt_text("Subscription ID", str(provider_cfg.get("subscription_id", "")).strip())
        provider_cfg["resource_group"] = _prompt_text("Resource Group", str(provider_cfg.get("resource_group", "")).strip())
        provider_cfg["zone_name"] = _prompt_text("Zone Name", str(provider_cfg.get("zone_name", "")).strip())
        provider_cfg["record_name"] = _prompt_text("记录名(record_name, 根记录用 @)", str(provider_cfg.get("record_name", "@")).strip())
        provider_cfg["ttl"] = _prompt_int("TTL", provider_cfg.get("ttl", 60), default_value=60, min_value=1)
        provider_cfg["api_version"] = _prompt_text("API Version", str(provider_cfg.get("api_version", "2018-05-01")).strip())

    if auto_save:
        save_config(config)
    return True


def ensure_dns_update_config_ready(config):
    provider = _get_dns_provider(config)
    missing = _missing_dns_config_fields(config)
    if not missing:
        print(f"DNS 更新配置检查通过：供应商 {_provider_name(provider)}")
        return True

    print(f"检测到 DNS 更新配置不完整（供应商: {_provider_name(provider)}）")
    print(f"缺少字段: {', '.join(missing)}")
    print("即将进入引导配置流程。")
    if not _run_dns_provider_wizard(config):
        print("已取消引导配置。")
        return False

    provider = _get_dns_provider(config)
    missing = _missing_dns_config_fields(config)
    if missing:
        print(f"配置仍不完整，缺少字段: {', '.join(missing)}")
        return False

    print(f"DNS 更新配置已保存并通过校验：供应商 {_provider_name(provider)}")
    return True


def _dns_optional_fields(provider):
    fields = {
        "dnspod": ["record_line", "ttl"],
        "aliyun": ["ttl", "endpoint"],
        "route53": ["session_token", "ttl"],
        "huawei": ["ttl", "base_url"],
        "gcp": ["ttl"],
        "azure": ["ttl", "api_version"],
    }
    return fields.get(provider, [])


def _extract_dns_profile_data(config, provider):
    provider = str(provider or "").strip().lower()
    if provider == "cloudflare":
        source = config.get("cloudflare", {})
    else:
        source = config.get("dns", {}).get(provider, {})

    keys = list(dict.fromkeys(_dns_required_fields(provider) + _dns_optional_fields(provider)))
    data = {}
    for key in keys:
        if key in source:
            data[key] = source.get(key)
    return data


def _dns_profile_target_label(provider, data):
    provider = str(provider or "").strip().lower()
    data = data if isinstance(data, dict) else {}
    if provider == "cloudflare":
        return str(data.get("dns_name", "未配置目标")).strip() or "未配置目标"
    if provider == "dnspod":
        domain = str(data.get("domain", "")).strip()
        sub = str(data.get("sub_domain", "@")).strip() or "@"
        if not domain:
            return "未配置目标"
        return domain if sub in ("@", "") else f"{sub}.{domain}"
    if provider == "aliyun":
        domain = str(data.get("domain", "")).strip()
        rr = str(data.get("rr", "@")).strip() or "@"
        if not domain:
            return "未配置目标"
        return domain if rr in ("@", "") else f"{rr}.{domain}"
    if provider in ("route53", "huawei", "gcp"):
        return str(data.get("record_name", "未配置目标")).strip() or "未配置目标"
    if provider == "azure":
        zone = str(data.get("zone_name", "")).strip()
        record = str(data.get("record_name", "")).strip()
        if not zone and not record:
            return "未配置目标"
        if record in ("", "@"):
            return zone or "未配置目标"
        return f"{record}.{zone}" if zone else record
    return "未配置目标"


def _dns_profile_default_name(provider, data):
    provider_text = _provider_name(provider)
    target = _dns_profile_target_label(provider, data)
    if target and target != "未配置目标":
        return f"{provider_text}-{target}"
    return provider_text


def _dns_profile_missing_fields(profile):
    provider = str(profile.get("provider", "")).strip().lower()
    data = profile.get("data", {}) if isinstance(profile.get("data"), dict) else {}
    missing = []
    for key in _dns_required_fields(provider):
        value = data.get(key)
        if value is None:
            missing.append(key)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(key)
    return missing


def _dns_profile_has_any_data(provider, data):
    for key in list(dict.fromkeys(_dns_required_fields(provider) + _dns_optional_fields(provider))):
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return True
            continue
        return True
    return False


def _build_dns_profile_from_config(config, profile_id=None, profile_name=None):
    provider = _get_dns_provider(config)
    data = _extract_dns_profile_data(config, provider)
    return {
        "id": profile_id or secrets.token_hex(8),
        "name": str(profile_name or _dns_profile_default_name(provider, data)).strip(),
        "provider": provider,
        "data": data,
    }


def _normalize_dns_profile_data(provider, data):
    provider = str(provider or "").strip().lower()
    data = data if isinstance(data, dict) else {}
    keys = list(dict.fromkeys(_dns_required_fields(provider) + _dns_optional_fields(provider)))
    normalized = {}
    for key in keys:
        if key not in data:
            continue
        value = data.get(key)
        if isinstance(value, str):
            value = value.strip()
        normalized[key] = value
    return normalized


def _dns_profile_signature(profile):
    provider = str(profile.get("provider", "")).strip().lower()
    data = _normalize_dns_profile_data(provider, profile.get("data", {}))
    return f"{provider}|{json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"


def _find_duplicate_profile(profiles, candidate_profile, exclude_id=None):
    candidate_sig = _dns_profile_signature(candidate_profile)
    exclude_id = str(exclude_id or "").strip()
    for profile in profiles:
        profile_id = str(profile.get("id", "")).strip()
        if exclude_id and profile_id == exclude_id:
            continue
        if _dns_profile_signature(profile) == candidate_sig:
            return profile
    return None


def _ensure_dns_profiles(config):
    settings = config.setdefault("settings", {})
    profiles = config.get("dns_profiles")
    if isinstance(profiles, list):
        normalized = []
        active_id = str(settings.get("active_dns_profile_id", "")).strip()
        seen_signature = {}
        duplicate_active_to = None
        should_save = False
        for item in profiles:
            if not isinstance(item, dict):
                continue
            provider = str(item.get("provider", "")).strip().lower()
            if not provider:
                continue
            raw_data = item.get("data", {})
            if isinstance(raw_data, dict):
                allowed_keys = list(dict.fromkeys(_dns_required_fields(provider) + _dns_optional_fields(provider)))
                data = {k: raw_data.get(k) for k in allowed_keys if k in raw_data}
            else:
                data = {}
            profile = {
                "id": str(item.get("id") or secrets.token_hex(8)),
                "name": str(item.get("name") or _dns_profile_default_name(provider, data)).strip(),
                "provider": provider,
                "data": data,
            }
            signature = _dns_profile_signature(profile)
            if signature in seen_signature:
                if active_id and profile["id"] == active_id:
                    duplicate_active_to = seen_signature[signature]
                should_save = True
                continue
            seen_signature[signature] = profile["id"]
            normalized.append(profile)

        if not normalized:
            legacy_provider = _get_dns_provider(config)
            legacy_data = _extract_dns_profile_data(config, legacy_provider)
            if _dns_profile_has_any_data(legacy_provider, legacy_data):
                migrated = {
                    "id": secrets.token_hex(8),
                    "name": _dns_profile_default_name(legacy_provider, legacy_data),
                    "provider": legacy_provider,
                    "data": legacy_data,
                }
                normalized.append(migrated)
                settings["active_dns_profile_id"] = migrated["id"]
                should_save = True

        normalized_ids = {str(p.get("id", "")) for p in normalized}
        if duplicate_active_to:
            settings["active_dns_profile_id"] = duplicate_active_to
            should_save = True
        elif active_id and active_id not in normalized_ids:
            settings["active_dns_profile_id"] = normalized[0]["id"] if normalized else ""
            should_save = True
        elif not active_id and normalized:
            settings["active_dns_profile_id"] = normalized[0]["id"]
            should_save = True

        legacy_cf = config.get("cloudflare")
        if isinstance(legacy_cf, dict):
            has_legacy_secret = any(
                str(legacy_cf.get(k, "")).strip()
                for k in ("api_token", "zone_id", "dns_name", "auth_key")
            )
            if has_legacy_secret:
                config["cloudflare"] = {}
                should_save = True

        if normalized != profiles:
            should_save = True

        if should_save:
            config["dns_profiles"] = normalized
            save_config(config)
        return normalized

    legacy_provider = _get_dns_provider(config)
    legacy_data = _extract_dns_profile_data(config, legacy_provider)
    if _dns_profile_has_any_data(legacy_provider, legacy_data):
        profile = {
            "id": secrets.token_hex(8),
            "name": _dns_profile_default_name(legacy_provider, legacy_data),
            "provider": legacy_provider,
            "data": legacy_data,
        }
        config["dns_profiles"] = [profile]
        if not str(settings.get("active_dns_profile_id", "")).strip():
            settings["active_dns_profile_id"] = profile["id"]
        config["cloudflare"] = {}
        save_config(config)
        return config["dns_profiles"]

    config["dns_profiles"] = []
    return config["dns_profiles"]


def _print_dns_profiles(config, show_index=True):
    profiles = _ensure_dns_profiles(config)
    active_id = str(config.get("settings", {}).get("active_dns_profile_id", "")).strip()
    if not profiles:
        print("当前没有待更新域名配置。")
        return
    print("当前待更新域名配置:")
    for i, profile in enumerate(profiles, start=1):
        provider = str(profile.get("provider", "")).strip().lower()
        provider_name = _provider_name(provider)
        target = _dns_profile_target_label(provider, profile.get("data", {}))
        missing = _dns_profile_missing_fields(profile)
        active_tag = " [当前]" if profile.get("id") == active_id else ""
        status = f"缺少: {','.join(missing)}" if missing else "完整"
        if show_index:
            print(f"{i}. {profile.get('name', '')} | {target} | {provider_name} | {status}{active_tag}")
        else:
            print(f"- {profile.get('name', '')} | {target} | {provider_name} | {status}{active_tag}")


def _select_dns_profile(config, prompt_text="请选择待更新域名配置序号", allow_back=False):
    profiles = _ensure_dns_profiles(config)
    if not profiles:
        return None

    settings = config.setdefault("settings", {})
    active_id = str(settings.get("active_dns_profile_id", "")).strip()
    default_index = 1
    for idx, profile in enumerate(profiles, start=1):
        if str(profile.get("id", "")).strip() == active_id:
            default_index = idx
            break

    _print_dns_profiles(config)
    if allow_back:
        print("B. 返回上层菜单")
    while True:
        hint = f"{prompt_text}（默认 {default_index}"
        if allow_back:
            hint += "，B=返回"
        hint += "）: "
        text = input(hint).strip()
        if allow_back and text.lower() == "b":
            return None
        if not text:
            selected_index = default_index
        else:
            try:
                selected_index = int(text)
            except ValueError:
                print("请输入有效序号。")
                continue
        if selected_index < 1 or selected_index > len(profiles):
            print("序号超出范围，请重试。")
            continue

        selected = profiles[selected_index - 1]
        settings["active_dns_profile_id"] = selected.get("id", "")
        save_config(config)
        return selected


def _apply_dns_profile_to_runtime_config(config, profile):
    provider = str(profile.get("provider", "")).strip().lower()
    data = profile.get("data", {}) if isinstance(profile.get("data"), dict) else {}

    dns_root = config.setdefault("dns", {})
    dns_root["provider"] = provider

    if provider == "cloudflare":
        cf = config.setdefault("cloudflare", {})
        cf.clear()
        cf.update(data)
        return

    provider_cfg = dns_root.setdefault(provider, {})
    provider_cfg.clear()
    provider_cfg.update(data)


def _build_empty_dns_wizard_config(config):
    default_provider = _get_dns_provider(config)
    return {
        "cloudflare": {
            "api_token": "",
            "zone_id": "",
            "dns_name": "",
        },
        "dns": {
            "provider": default_provider,
            "dnspod": {
                "secret_id": "",
                "secret_key": "",
                "domain": "",
                "sub_domain": "@",
                "record_line": "默认",
                "ttl": 60,
            },
            "aliyun": {
                "access_key_id": "",
                "access_key_secret": "",
                "domain": "",
                "rr": "@",
                "ttl": 60,
                "endpoint": "https://alidns.aliyuncs.com/",
            },
            "route53": {
                "access_key_id": "",
                "secret_access_key": "",
                "session_token": "",
                "hosted_zone_id": "",
                "record_name": "",
                "ttl": 60,
            },
            "huawei": {
                "token": "",
                "zone_id": "",
                "record_name": "",
                "ttl": 60,
                "base_url": "https://dns.myhuaweicloud.com",
            },
            "gcp": {
                "access_token": "",
                "project_id": "",
                "managed_zone": "",
                "record_name": "",
                "ttl": 60,
            },
            "azure": {
                "access_token": "",
                "subscription_id": "",
                "resource_group": "",
                "zone_name": "",
                "record_name": "@",
                "ttl": 60,
                "api_version": "2018-05-01",
            },
        },
    }


def _verify_dns_profile(config, profile):
    provider = str(profile.get("provider", "")).strip().lower()
    provider_name = _provider_name(provider)
    target_label = _dns_profile_target_label(provider, profile.get("data", {}))
    verify_cfg = copy.deepcopy(config)
    _apply_dns_profile_to_runtime_config(verify_cfg, profile)
    verify_cfg.setdefault("settings", {})["_runtime_quiet_cloudflare"] = True

    print(f"正在验证配置可用性：{provider_name} | {target_label}")

    if provider == "cloudflare":
        ok, current_ip, reason = _verify_cloudflare_profile(verify_cfg, target_label)
        if not ok:
            print(reason)
            return False
        print(f"验证通过：{target_label} 当前解析 IP = {current_ip}")
        return True

    ok, current_ip, reason = _verify_other_provider_profile(verify_cfg, provider, target_label)
    if not ok:
        print(reason)
        return False

    print(f"验证通过：{target_label} 当前解析 IP = {current_ip}")
    return True


def _verify_cloudflare_profile(config, target_label):
    """Cloudflare 专用验证：区分凭据错误与无 A 记录。"""
    try:
        dns_name = str(config.get("cloudflare", {}).get("dns_name", "")).strip()
        if not dns_name:
            return False, None, "验证失败：Cloudflare 域名配置为空，请填写需要更新的域名。"
        res = cloudflare_request(config, "GET", params={"name": dns_name})
    except Exception:
        return False, None, "验证失败：Cloudflare 接口请求失败，请检查网络后重试。"

    if res is None:
        return False, None, "验证失败：Cloudflare 接口不可用，请检查网络后重试。"

    status = getattr(res, "status_code", 0)
    body = {}
    try:
        body = res.json()
    except Exception:
        body = {}

    if status in (401, 403):
        return False, None, "验证失败：Cloudflare API Token 无效或权限不足。"
    if status == 404:
        return False, None, "验证失败：Cloudflare Zone ID 可能错误或无访问权限。"
    if status != 200:
        return False, None, f"验证失败：Cloudflare 接口返回异常（HTTP {status}）。"

    if isinstance(body, dict) and body.get("success") is False:
        errors = body.get("errors", [])
        err_code = ""
        err_msg = ""
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                err_code = str(first.get("code", "")).strip()
                err_msg = str(first.get("message", "")).strip()
        if err_code in {"10000", "10001", "9109"}:
            return False, None, "验证失败：Cloudflare API Token 无效、过期或权限不足。"
        if err_code in {"7003", "7000"}:
            return False, None, "验证失败：Cloudflare Zone ID 可能错误。"
        if err_msg:
            return False, None, f"验证失败：Cloudflare 接口返回错误（{err_msg}）。"
        return False, None, "验证失败：Cloudflare 接口返回错误，请检查配置。"

    records = []
    if isinstance(body, dict):
        result = body.get("result", [])
        if isinstance(result, list):
            records = result
    a_records = [r for r in records if str(r.get("type", "")).upper() == "A"]
    if not a_records:
        return False, None, f"验证失败：未找到 {target_label} 的 A 记录。请先在DNS控制面板增加A记录，再运行软件。"

    current_ip = str(a_records[0].get("content", "")).strip() or "未知"
    return True, current_ip, ""


def _verify_missing_a_record_message(target_label):
    return f"验证失败：未找到 {target_label} 的 A 记录。请先在DNS控制面板增加A记录，再运行软件。"


def _verify_http_status(exc):
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None)


def _verify_error_blob(exc):
    chunks = [str(exc)]
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            payload = resp.json()
            chunks.append(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass
        try:
            txt = resp.text
        except Exception:
            txt = ""
        if txt:
            chunks.append(txt)
    return " ".join(chunks).lower()


def _verify_other_provider_profile(config, provider, target_label):
    if provider == "azure":
        return _verify_azure_profile(config, target_label)
    try:
        current_ip = get_current_dns_ip(config)
    except Exception as exc:
        return False, None, _verify_provider_error_message(provider, exc, target_label)

    if not current_ip:
        return False, None, _verify_missing_a_record_message(target_label)
    return True, current_ip, ""


def _verify_provider_error_message(provider, exc, target_label):
    provider_name = _provider_name(provider)
    if isinstance(exc, ValueError):
        return f"验证失败：{provider_name} 配置不完整，请补全必填字段后重试。"
    if isinstance(exc, requests.exceptions.Timeout):
        return f"验证失败：{provider_name} 接口请求超时，请稍后重试。"
    if isinstance(exc, requests.exceptions.SSLError):
        return f"验证失败：{provider_name} SSL 连接失败，请检查网络环境。"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return f"验证失败：{provider_name} 网络连接失败，请检查网络后重试。"

    status = _verify_http_status(exc)
    text = _verify_error_blob(exc)

    def has_any(words):
        return any(w in text for w in words)

    if provider == "dnspod":
        if status in (401, 403) or has_any([
            "authfailure", "secretidnotfound", "signaturefailure",
            "unauthorizedoperation", "secret key", "secretid", "无权限"
        ]):
            return "验证失败：DNSPod 凭据无效或权限不足。"
        if status == 404 or has_any([
            "invalidparameter.domain", "resourcenotfound.domain",
            "domainnotexists", "subdomain", "recordline"
        ]):
            return f"验证失败：DNSPod 域名配置有误（请检查 Domain/SubDomain）。"

    if provider == "aliyun":
        if status in (401, 403) or has_any([
            "invalidaccesskeyid", "signaturedoesnotmatch",
            "invalidsecuritytoken", "forbidden", "unauthorized"
        ]):
            return "验证失败：阿里云 AccessKey 无效或权限不足。"
        if status == 404 or has_any([
            "domainnotbelongtouser", "domainrecordnotbelongtouser",
            "domainnameinvalid", "invaliddomainname", "missingparameter"
        ]):
            return "验证失败：阿里云域名配置有误（请检查域名与 RR 设置）。"

    if provider == "route53":
        if status in (401, 403) or has_any([
            "invalidclienttokenid", "signaturedoesnotmatch",
            "accessdenied", "expiredtoken", "missingauthenticationtoken"
        ]):
            return "验证失败：Route53 凭据无效或权限不足。"
        if status in (400, 404) or has_any([
            "nosuchhostedzone", "hosted zone", "invalidinput"
        ]):
            return "验证失败：Route53 Hosted Zone 或记录名称配置有误。"

    if provider == "huawei":
        if status in (401, 403) or has_any([
            "x-auth-token", "token", "unauthorized", "forbidden", "apigw.0301"
        ]):
            return "验证失败：华为云 Token 无效或权限不足。"
        if status in (400, 404) or has_any(["zone", "recordset", "not found", "dns."]):
            return "验证失败：华为云 Zone ID 或记录名称配置有误。"

    if provider == "gcp":
        if status in (401, 403) or has_any([
            "unauthenticated", "invalid credentials",
            "permissiondenied", "insufficient authentication scopes"
        ]):
            return "验证失败：Google Cloud DNS Access Token 无效或权限不足。"
        if status in (400, 404) or has_any(["managedzone", "project", "not found"]):
            return "验证失败：Google Cloud DNS 项目、托管区或记录名称配置有误。"

    if provider == "azure":
        if status in (401, 403) or has_any([
            "invalidauthenticationtoken", "authorizationfailed",
            "expiredauthenticationtoken", "authenticationfailed"
        ]):
            return "验证失败：Azure DNS Access Token 无效或权限不足。"
        if status in (400, 404) or has_any([
            "parentresourcenotfound", "resourcenotfound", "dnszones", "resource group"
        ]):
            return "验证失败：Azure DNS 订阅、资源组、Zone 或记录配置有误。"

    if isinstance(exc, requests.exceptions.HTTPError) and status:
        return f"验证失败：{provider_name} 接口返回异常（HTTP {status}）。"

    return f"验证失败：{provider_name} 接口校验失败，请检查网络或凭据配置。"


def _verify_azure_profile(config, target_label):
    try:
        current_ip = get_current_dns_ip_azure(config)
    except Exception as exc:
        return False, None, _verify_provider_error_message("azure", exc, target_label)

    if current_ip:
        return True, current_ip, ""

    try:
        dns_cfg = config.get("dns", {}).get("azure", {})
        subscription_id = _dns_required(dns_cfg, "subscription_id", "azure")
        resource_group = _dns_required(dns_cfg, "resource_group", "azure")
        zone_name = _dns_required(dns_cfg, "zone_name", "azure")
        api_version = str(dns_cfg.get("api_version", "2018-05-01")).strip()
        zone_url = (
            "https://management.azure.com/"
            f"subscriptions/{subscription_id}/resourceGroups/{resource_group}/"
            f"providers/Microsoft.Network/dnsZones/{zone_name}"
            f"?api-version={api_version}"
        )
        zone_resp = requests.get(zone_url, headers=_azure_headers(config), timeout=15)
    except Exception as exc:
        return False, None, _verify_provider_error_message("azure", exc, target_label)

    if zone_resp.status_code == 200:
        return False, None, _verify_missing_a_record_message(target_label)
    if zone_resp.status_code in (401, 403):
        return False, None, "验证失败：Azure DNS Access Token 无效或权限不足。"
    if zone_resp.status_code == 404:
        return False, None, "验证失败：Azure DNS 订阅、资源组或 Zone 配置有误。"
    return False, None, f"验证失败：Azure DNS 接口返回异常（HTTP {zone_resp.status_code}）。"


def _create_dns_profile(config):
    temp_cfg = _build_empty_dns_wizard_config(config)
    if not _run_dns_provider_wizard(temp_cfg, auto_save=False):
        print("已取消新增配置。")
        return False
    new_profile = _build_dns_profile_from_config(temp_cfg)
    missing = _dns_profile_missing_fields(new_profile)
    if missing:
        print(f"新增失败：配置不完整，缺少字段: {', '.join(missing)}")
        return False

    profiles = _ensure_dns_profiles(config)
    duplicate = _find_duplicate_profile(profiles, new_profile)
    if duplicate:
        config.setdefault("settings", {})["active_dns_profile_id"] = duplicate.get("id", "")
        save_config(config)
        print(f"检测到重复配置，已存在：{duplicate.get('name', '')}")
        print("已切换到该配置，不重复新增。")
        return True

    default_name = _dns_profile_default_name(new_profile["provider"], new_profile["data"])
    name_input = input(f"请输入配置名称（回车默认: {default_name}）: ").strip()
    new_profile["name"] = name_input or default_name
    if not _verify_dns_profile(config, new_profile):
        print("新增失败：配置验证未通过，请检查后重试。")
        return False

    profiles = _ensure_dns_profiles(config)
    profiles.append(new_profile)
    config["dns_profiles"] = profiles
    config.setdefault("settings", {})["active_dns_profile_id"] = new_profile["id"]
    save_config(config)
    print(f"已新增配置: {new_profile['name']}")
    return True


def _edit_dns_profile(config):
    profiles = _ensure_dns_profiles(config)
    if not profiles:
        print("当前没有可修改的配置。")
        return False

    selected = _select_dns_profile(config, prompt_text="请选择要修改的配置序号")
    if not selected:
        return False

    temp_cfg = copy.deepcopy(config)
    _apply_dns_profile_to_runtime_config(temp_cfg, selected)
    if not _run_dns_provider_wizard(temp_cfg, auto_save=False):
        print("已取消修改配置。")
        return False
    updated = _build_dns_profile_from_config(
        temp_cfg,
        profile_id=str(selected.get("id", "")),
        profile_name=str(selected.get("name", "")).strip(),
    )
    missing = _dns_profile_missing_fields(updated)
    if missing:
        print(f"修改失败：配置不完整，缺少字段: {', '.join(missing)}")
        return False

    duplicate = _find_duplicate_profile(profiles, updated, exclude_id=selected.get("id", ""))
    if duplicate:
        config.setdefault("settings", {})["active_dns_profile_id"] = duplicate.get("id", "")
        save_config(config)
        print(f"检测到与现有配置重复：{duplicate.get('name', '')}")
        print("已切换到现有配置，本次修改未保存。")
        return True

    default_name = str(selected.get("name", "")).strip() or _dns_profile_default_name(updated["provider"], updated["data"])
    name_input = input(f"配置名称（回车沿用: {default_name}）: ").strip()
    updated["name"] = name_input or default_name
    if not _verify_dns_profile(config, updated):
        print("修改失败：配置验证未通过，请检查后重试。")
        return False

    for i, profile in enumerate(profiles):
        if str(profile.get("id", "")) == str(updated.get("id", "")):
            profiles[i] = updated
            break
    config["dns_profiles"] = profiles
    config.setdefault("settings", {})["active_dns_profile_id"] = updated["id"]
    save_config(config)
    print(f"已更新配置: {updated['name']}")
    return True


def _delete_dns_profile(config):
    profiles = _ensure_dns_profiles(config)
    if not profiles:
        print("当前没有可删除的配置。")
        return False

    selected = _select_dns_profile(config, prompt_text="请选择要删除的配置序号")
    if not selected:
        return False

    confirm = input(f"确认删除配置 [{selected.get('name', '')}]？（输入Y并回车确认取消）: ").strip().lower()
    if confirm != "y":
        print("已取消删除。")
        return False

    keep = [item for item in profiles if str(item.get("id", "")) != str(selected.get("id", ""))]
    config["dns_profiles"] = keep
    settings = config.setdefault("settings", {})
    if str(settings.get("active_dns_profile_id", "")) == str(selected.get("id", "")):
        settings["active_dns_profile_id"] = keep[0]["id"] if keep else ""
    save_config(config)
    print("删除成功。")
    return True


def manage_dns_profiles(config):
    while True:
        print("\n待更新域名配置管理：")
        _print_dns_profiles(config, show_index=False)
        print("1、新增配置")
        print("2、修改配置")
        print("3、删除配置")
        print("4、返回上一级")
        action = input("> ").strip()
        if not action:
            action = "4"

        if action == "1":
            _create_dns_profile(config)
            continue
        if action == "2":
            _edit_dns_profile(config)
            continue
        if action == "3":
            _delete_dns_profile(config)
            continue
        if action == "4":
            return
        print("无效输入，请重试。")


def _parse_telegram_chat_ids(raw_value):
    return [c.strip() for c in str(raw_value or "").split(",") if c.strip()]


def _mask_chat_id(chat_id):
    chat_id = str(chat_id or "").strip()
    if len(chat_id) <= 4:
        return chat_id or "未知"
    return f"{chat_id[:2]}***{chat_id[-2:]}"


def _send_telegram_message(config, chat_id, text, parse_mode="HTML", disable_web_page_preview=True, timeout=10):
    tg = config.get("telegram", {})
    token = str(tg.get("bot_token", "")).strip()
    if not token:
        return False, "未配置 Telegram Bot Token"
    if not chat_id:
        return False, "未配置 Telegram Chat ID"

    base_url = _get_preferred_worker_base_url(config).rstrip("/")
    auth_key = _get_admin_auth_key(config)
    req_headers = {"x-auth-key": auth_key} if auth_key else {}
    proxy_url = f"{base_url}/tg/bot{token}/sendMessage"
    direct_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": str(chat_id).strip(),
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview
    }

    def _parse_tg_error(status, body):
        if isinstance(body, dict):
            if str(body.get("error", "")).strip().lower() == "access denied":
                return "TG代理鉴权失败（缺少或错误 auth_key）"
            desc = str(body.get("description", "")).strip()
            low = desc.lower()
            if "chat not found" in low:
                return "Chat ID 无效或机器人未建立会话（请先私聊机器人并发送 /start）"
            if "bot was blocked by the user" in low:
                return "机器人被该用户屏蔽（请先取消屏蔽并发送 /start）"
            if "forbidden" in low and desc:
                return f"权限错误（{desc}）"
            if desc:
                return desc
        return f"HTTP {status}"

    def _post(url, headers):
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        status = getattr(resp, "status_code", 0)
        body = {}
        try:
            body = resp.json()
        except Exception:
            body = {}
        if status == 200 and (not isinstance(body, dict) or body.get("ok") is not False):
            return True, ""
        return False, _parse_tg_error(status, body)

    try:
        ok, reason = _post(proxy_url, req_headers)
    except Exception as e:
        ok, reason = False, _brief_request_error(e)
    if ok:
        return True, ""

    should_fallback_direct = reason.startswith("TG代理鉴权失败") or reason.startswith("HTTP 404")
    if should_fallback_direct:
        try:
            return _post(direct_url, {})
        except Exception as e:
            return False, _brief_request_error(e)
    return False, reason


def configure_telegram_push(config):
    tg = config.setdefault("telegram", {})
    print("\nTelegram Bot 推送设置：")
    tg["bot_token"] = _prompt_text(
        "Bot Token（填写你申请的Telegram Bot Token）",
        str(tg.get("bot_token", "")).strip(),
        allow_empty=True,
    )
    tg["chat_id"] = _prompt_text(
        "Chat ID（填写你的Telegram ID,可通过@userinfobot查询）",
        str(tg.get("chat_id", "")).strip(),
        allow_empty=True,
    )
    save_config(config)
    print("Telegram 推送配置已保存。")

    token = str(tg.get("bot_token", "")).strip()
    chat_ids = _parse_telegram_chat_ids(tg.get("chat_id", ""))
    if not token or not chat_ids:
        print("提示：Bot Token 或 Chat ID 为空，已跳过有效性验证。")
        return

    if not re.match(r"^\d{6,}:[A-Za-z0-9_-]{20,}$", token):
        print("提示：Bot Token 格式可能不正确，仍尝试进行连通性验证。")

    print("正在验证 Telegram 推送配置并发送测试消息...")
    test_text = (
        "✅ <b>Telegram 推送配置验证成功</b>\n"
        "<b>说明:</b> 后续测速与DNS更新结果将推送到此会话。"
    )
    success_count = 0
    for chat_id in chat_ids:
        ok, reason = _send_telegram_message(
            config,
            chat_id,
            test_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            timeout=10
        )
        if ok:
            success_count += 1
            print(f"  ✓ 验证消息已发送至 {_mask_chat_id(chat_id)}")
        else:
            print(f"  ✗ {_mask_chat_id(chat_id)} 验证失败（{reason}）")
    if success_count == len(chat_ids):
        print("Telegram 配置验证通过。")
    elif success_count > 0:
        print("Telegram 配置部分通过，请检查失败的 Chat ID。")
    else:
        print("Telegram 配置验证失败，请检查 Bot Token、Chat ID 或网络后重试。")


def manage_system_settings(config):
    while True:
        print("\n系统设置：")
        print("1、设置Telegram Bot推送(用于推送系统相关测速结果信息)")
        print("2、设置自定义优选IP源地址（根据https://github.com/wzlinbin/CloudFlareIP-RenewDNS 私有化部署CF Worker优选IP汇聚源）")
        print("3、返回上一级")
        action = input("> ").strip()
        if not action:
            action = "3"

        if action == "1":
            configure_telegram_push(config)
            continue
        if action == "2":
            custom_url = configure_custom_ip_source(
                config,
                allow_blank_use_existing=True,
                allow_back=True,
            )
            if not custom_url:
                print("已返回系统设置。")
                continue
            print(f"当前自定义优选IP源: {custom_url}")
            continue
        if action == "3":
            return
        print("无效输入，请重试。")


# ============================================================
# Cloudflare 数据获取助手
# ============================================================
def cloudflare_request(config, method, url_suffix="", **kwargs):
    """统一请求入口：直连优先，失败回退到代理"""
    zone_id = config['cloudflare']['zone_id']
    token = config['cloudflare']['api_token']
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    base_url = _get_preferred_worker_base_url(config).rstrip('/')
    auth_key = (
        config.get('cloudflare', {}).get('auth_key')
        or _get_admin_auth_key(config)
    )
    quiet_mode = bool(config.get("settings", {}).get("_runtime_quiet_cloudflare"))

    direct_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records{url_suffix}"
    
    # 尝试直连
    try:
        if not quiet_mode:
            print("正在连接 Cloudflare 接口...")
        res = requests.request(method, direct_url, headers=headers, timeout=10, **kwargs)
        if res.status_code == 200:
            return res
        if not quiet_mode:
            print("Cloudflare 直连不可用，已切换代理通道。")
    except Exception:
        if not quiet_mode:
            print("Cloudflare 直连不可用，已切换代理通道。")

    # 回退代理
    if "api.cloudflare.com" in base_url:
        return None
        
    proxy_headers = headers.copy()
    if auth_key:
        proxy_headers["x-auth-key"] = auth_key
    
    proxy_url = f"{base_url}/cf/client/v4/zones/{zone_id}/dns_records{url_suffix}"
    
    try:
        if not quiet_mode:
            print("正在通过代理通道访问 Cloudflare...")
        res = requests.request(method, proxy_url, headers=proxy_headers, timeout=15, **kwargs)
        return res
    except Exception:
        if not quiet_mode:
            print("Cloudflare 接口暂不可用。")
        return None


def get_current_dns_ip_cloudflare(config):
    """获取域名当前在 Cloudflare 上的解析 IP"""
    dns_name = config['cloudflare']['dns_name']
    res = cloudflare_request(config, "GET", params={"name": dns_name})
    if res and res.status_code == 200:
        records = res.json().get('result', [])
        if records:
            return records[0]['content']
    return None


# ============================================================
# IP 采集模块（并发请求所有源）
# ============================================================
def fetch_ips(config, current_ip=None):
    """从统一接口拉取 IP，并与当前解析 IP 合并后写入 ip.txt"""
    settings = config.get('settings', {})
    source_urls = _resolve_ip_source_urls(settings)
    timeout = _safe_int(settings.get('timeout', 15), 15, min_value=1)
    ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
    all_ips = set()
    success_count = 0

    if current_ip:
        all_ips.add(current_ip)
        print(f"已将当前解析 IP {current_ip} 加入测速池进行对比。")

    for source_url in source_urls:
        headers, auth_mode = _build_ip_api_headers(config, source_url, timeout)
        try:
            if auth_mode == "none-custom":
                print("正在从自建IP源获取 IP 数据...")
            else:
                print("正在从软件官方接口获取 IP 数据...")
            resp = requests.get(source_url, headers=headers, timeout=timeout)
            resp.raise_for_status()

            api_ips = []
            try:
                payload = resp.json()
                unique_ips = payload.get("global", {}).get("unique_ips", [])
                if isinstance(unique_ips, list):
                    api_ips.extend([str(ip).strip() for ip in unique_ips if str(ip).strip()])
            except Exception:
                pass

            if not api_ips:
                api_ips = re.findall(ip_pattern, resp.text)

            all_ips.update(api_ips)
            success_count += 1
            print(f"接口返回 {len(api_ips)} 条 IPv4，当前去重后共 {len(all_ips)} 条待测速。")
        except Exception as e:
            print(f"错误: IP源获取失败（{_brief_request_error(e)}）。")

    if success_count == 0:
        if os.path.exists('ip.txt') and os.path.getsize('ip.txt') > 0:
            print("检测到现有的 ip.txt 文件，将使用缓存的 IP 数据继续测速。")
            return True
        return False

    if not all_ips:
        print("错误: 接口未返回有效 IP 地址。")
        return False

    with open('ip.txt', 'w', encoding='utf-8') as f:
        for ip in sorted(all_ips):
            f.write(f"{ip}\n")
    return True

def run_speed_test(config):
    """运行 CloudflareSpeedTest 并解析生成的 CSV 结果"""
    print("正在运行 CloudflareSpeedTest...")
    if not os.path.exists('cfst.exe'):
        print("错误: 未找到 cfst.exe，请确保它位于项目根目录下。")
        return None, None, None

    max_test = _safe_int(config.get('settings', {}).get('max_ips', 200), 200, min_value=1)
    top_n    = _safe_int(config.get('settings', {}).get('top_n', 10), 10, min_value=1)

    try:
        subprocess.run(
            ['cfst.exe', '-f', 'ip.txt', '-o', 'result.csv',
             '-n', str(max_test), '-dn', str(top_n)],
            input='\n', text=True, check=True, timeout=300
        )
        if os.path.exists('result.csv'):
            content = None
            for enc in ['utf-8', 'gbk', 'utf-8-sig']:
                try:
                    with open('result.csv', 'r', encoding=enc) as f:
                        content = f.read()
                    break
                except Exception:
                    continue
            if content:
                with open('result.csv', 'w', encoding='utf-8-sig') as f:
                    f.write(content)
            with open('result.csv', 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                first_row = next(reader, None)
                if first_row:
                    ip_key     = next((k for k in first_row if 'IP' in k), 'IP 地址')
                    speed_key  = next((k for k in first_row if '下载' in k and 'MB/s' in k), '下载速度(MB/s)')
                    region_key = next((k for k in first_row if '地区' in k), '地区码')
                    best_ip       = first_row.get(ip_key)
                    download_speed = first_row.get(speed_key)
                    region_code   = first_row.get(region_key, '未知')
                    if best_ip:
                        print(f"最优 IP: {best_ip}, 地区: {region_code}, 下载速度: {download_speed} MB/s")
                        return best_ip, download_speed, region_code
        return None, None, None
    except subprocess.TimeoutExpired:
        print("错误: CloudflareSpeedTest 运行超时（超过 300 秒），请检查网络环境。")
        return None, None, None
    except Exception as e:
        print(f"运行测速时发生错误: {e}")
        return None, None, None


# ============================================================
# Cloudflare DNS 更新模块
# ============================================================
def update_dns_cloudflare(config, new_ip):
    """通过 Cloudflare API 更新 A 记录"""
    dns_name = config['cloudflare']['dns_name']
    
    print(f"正在准备更新 Cloudflare DNS 记录 {dns_name} 为 {new_ip}...")
    
    # 1. 获取记录 ID
    res = cloudflare_request(config, "GET", params={"name": dns_name})
    if not res or res.status_code != 200:
        print(f"未能获取域名解析记录列表，请检查网络或配置。")
        return False
        
    records = res.json().get('result', [])
    if not records:
        print(f"错误: 未找到域名 {dns_name} 的解析记录。")
        return False
        
    record_id  = records[0]['id']
    current_ip = records[0]['content']
    
    if current_ip == new_ip:
        print("当前 IP 已是最优，无需更新。")
        return "NO_CHANGE"
        
    # 2. 执行更新
    put_res = cloudflare_request(
        config, "PUT", url_suffix=f"/{record_id}",
        json={"type":"A","name":dns_name,"content":new_ip,"ttl":60,"proxied":False}
    )
    
    if put_res and put_res.status_code == 200 and put_res.json().get('success'):
        print("DNS 更新成功！")
        return True
    else:
        err_info = put_res.text if put_res else "无响应"
        print(f"更新失败: {err_info}")
        return False


def _get_dns_provider(config):
    dns_cfg = config.get("dns", {})
    provider = str(dns_cfg.get("provider", "cloudflare")).strip().lower()
    return provider or "cloudflare"


def _provider_name(provider):
    mapping = {
        "cloudflare": "Cloudflare",
        "dnspod": "DNSPod",
        "aliyun": "阿里云DNS",
        "route53": "AWS Route53",
        "huawei": "华为云DNS",
        "gcp": "Google Cloud DNS",
        "azure": "Azure DNS"
    }
    return mapping.get(provider, provider)


def _get_dns_target_label(config):
    provider = _get_dns_provider(config)
    if provider == "cloudflare":
        return str(config.get("cloudflare", {}).get("dns_name", "未配置目标")).strip()
    if provider == "dnspod":
        cfg = config.get("dns", {}).get("dnspod", {})
        domain = str(cfg.get("domain", "")).strip()
        sub = str(cfg.get("sub_domain", "@")).strip() or "@"
        if not domain:
            return "未配置目标"
        return domain if sub in ("@", "") else f"{sub}.{domain}"
    if provider == "aliyun":
        cfg = config.get("dns", {}).get("aliyun", {})
        domain = str(cfg.get("domain", "")).strip()
        rr = str(cfg.get("rr", "@")).strip() or "@"
        if not domain:
            return "未配置目标"
        return domain if rr in ("@", "") else f"{rr}.{domain}"
    if provider == "route53":
        return str(config.get("dns", {}).get("route53", {}).get("record_name", "未配置目标")).strip()
    if provider == "huawei":
        return str(config.get("dns", {}).get("huawei", {}).get("record_name", "未配置目标")).strip()
    if provider == "gcp":
        return str(config.get("dns", {}).get("gcp", {}).get("record_name", "未配置目标")).strip()
    if provider == "azure":
        cfg = config.get("dns", {}).get("azure", {})
        zone = str(cfg.get("zone_name", "")).strip()
        record = str(cfg.get("record_name", "")).strip()
        if not zone and not record:
            return "未配置目标"
        if record in ("", "@"):
            return zone
        return f"{record}.{zone}" if zone else record
    return "未配置目标"


def _dns_required(cfg, key, provider):
    value = cfg.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{_provider_name(provider)} 配置缺少字段: {key}")
    return value


def _ensure_fqdn(name):
    value = str(name).strip()
    if not value:
        return value
    return value if value.endswith(".") else f"{value}."


def _tc3_hmac_sha256(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _dnspod_request(config, action, payload):
    dns_cfg = config.get("dns", {}).get("dnspod", {})
    secret_id = _dns_required(dns_cfg, "secret_id", "dnspod")
    secret_key = _dns_required(dns_cfg, "secret_key", "dnspod")
    region = str(dns_cfg.get("region", "")).strip()
    service = "dnspod"
    host = "dnspod.tencentcloudapi.com"
    endpoint = f"https://{host}"
    version = "2021-03-23"
    algorithm = "TC3-HMAC-SHA256"
    timestamp = int(time.time())
    date = datetime.datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    content_type = "application/json; charset=utf-8"

    canonical_headers = f"content-type:{content_type}\nhost:{host}\n"
    signed_headers = "content-type;host"
    hashed_request_payload = hashlib.sha256(body.encode("utf-8")).hexdigest()
    canonical_request = (
        "POST\n"
        "/\n"
        "\n"
        f"{canonical_headers}\n"
        f"{signed_headers}\n"
        f"{hashed_request_payload}"
    )
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = (
        f"{algorithm}\n"
        f"{timestamp}\n"
        f"{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )
    secret_date = _tc3_hmac_sha256(f"TC3{secret_key}".encode("utf-8"), date)
    secret_service = hmac.new(secret_date, service.encode("utf-8"), hashlib.sha256).digest()
    secret_signing = hmac.new(secret_service, b"tc3_request", hashlib.sha256).digest()
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"{algorithm} Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "Authorization": authorization,
        "Content-Type": content_type,
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
    }
    if region:
        headers["X-TC-Region"] = region

    resp = requests.post(endpoint, headers=headers, data=body.encode("utf-8"), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    err = data.get("Response", {}).get("Error")
    if err:
        code = err.get("Code", "Unknown")
        message = err.get("Message", "Unknown")
        raise RuntimeError(f"DNSPod API 错误: {code} {message}")
    return data.get("Response", {})


def get_current_dns_ip_dnspod(config):
    dns_cfg = config.get("dns", {}).get("dnspod", {})
    domain = _dns_required(dns_cfg, "domain", "dnspod")
    sub_domain = str(dns_cfg.get("sub_domain", "@")).strip() or "@"
    payload = {
        "Domain": domain,
        "Subdomain": sub_domain,
        "RecordType": "A",
        "Limit": 20
    }
    resp = _dnspod_request(config, "DescribeRecordList", payload)
    records = resp.get("RecordList", []) or []
    for record in records:
        if str(record.get("Type", "")).upper() == "A":
            return record.get("Value")
    return None


def update_dns_dnspod(config, new_ip):
    dns_cfg = config.get("dns", {}).get("dnspod", {})
    domain = _dns_required(dns_cfg, "domain", "dnspod")
    sub_domain = str(dns_cfg.get("sub_domain", "@")).strip() or "@"
    record_line = str(dns_cfg.get("record_line", "默认")).strip() or "默认"
    ttl = _safe_int(dns_cfg.get("ttl", 60), 60, min_value=1)

    payload = {
        "Domain": domain,
        "Subdomain": sub_domain,
        "RecordType": "A",
        "RecordLine": record_line,
        "Limit": 20
    }
    resp = _dnspod_request(config, "DescribeRecordList", payload)
    records = resp.get("RecordList", []) or []
    target = None
    for record in records:
        if str(record.get("Type", "")).upper() != "A":
            continue
        if str(record.get("Line", "")) == record_line:
            target = record
            break
        if target is None:
            target = record

    if target and target.get("Value") == new_ip:
        print("当前 IP 已是最优，无需更新。")
        return "NO_CHANGE"

    if target:
        modify_payload = {
            "Domain": domain,
            "SubDomain": sub_domain,
            "RecordType": "A",
            "RecordLine": target.get("Line", record_line),
            "Value": new_ip,
            "RecordId": int(target["RecordId"]),
            "TTL": ttl
        }
        _dnspod_request(config, "ModifyRecord", modify_payload)
    else:
        create_payload = {
            "Domain": domain,
            "SubDomain": sub_domain,
            "RecordType": "A",
            "RecordLine": record_line,
            "Value": new_ip,
            "TTL": ttl
        }
        _dnspod_request(config, "CreateRecord", create_payload)
    print("DNS 更新成功！")
    return True


def _aliyun_percent_encode(value):
    encoded = quote(str(value), safe='~')
    return encoded.replace("+", "%20").replace("*", "%2A").replace("%7E", "~")


def _aliyun_request(config, action, extra_params):
    dns_cfg = config.get("dns", {}).get("aliyun", {})
    access_key_id = _dns_required(dns_cfg, "access_key_id", "aliyun")
    access_key_secret = _dns_required(dns_cfg, "access_key_secret", "aliyun")
    endpoint = str(dns_cfg.get("endpoint", "https://alidns.aliyuncs.com/")).strip()
    nonce = str(uuid.uuid4())
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "Format": "JSON",
        "Version": "2015-01-09",
        "AccessKeyId": access_key_id,
        "SignatureMethod": "HMAC-SHA1",
        "Timestamp": timestamp,
        "SignatureVersion": "1.0",
        "SignatureNonce": nonce,
        "Action": action
    }
    params.update(extra_params)
    sorted_params = sorted(params.items(), key=lambda x: x[0])
    canonicalized_query = "&".join(
        f"{_aliyun_percent_encode(k)}={_aliyun_percent_encode(v)}"
        for k, v in sorted_params
    )
    string_to_sign = f"GET&%2F&{_aliyun_percent_encode(canonicalized_query)}"
    signature = base64.b64encode(
        hmac.new(f"{access_key_secret}&".encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")
    params["Signature"] = signature
    resp = requests.get(endpoint, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "Code" in data and "Message" in data:
        raise RuntimeError(f"阿里云DNS API 错误: {data['Code']} {data['Message']}")
    return data


def get_current_dns_ip_aliyun(config):
    dns_cfg = config.get("dns", {}).get("aliyun", {})
    domain = _dns_required(dns_cfg, "domain", "aliyun")
    rr = str(dns_cfg.get("rr", "@")).strip() or "@"
    sub_domain = domain if rr == "@" else f"{rr}.{domain}"
    data = _aliyun_request(config, "DescribeSubDomainRecords", {
        "SubDomain": sub_domain,
        "Type": "A",
        "PageSize": 20
    })
    records = data.get("DomainRecords", {}).get("Record", [])
    if isinstance(records, dict):
        records = [records]
    for record in records:
        if str(record.get("Type", "")).upper() == "A":
            return record.get("Value")
    return None


def update_dns_aliyun(config, new_ip):
    dns_cfg = config.get("dns", {}).get("aliyun", {})
    domain = _dns_required(dns_cfg, "domain", "aliyun")
    rr = str(dns_cfg.get("rr", "@")).strip() or "@"
    ttl = _safe_int(dns_cfg.get("ttl", 60), 60, min_value=1)
    sub_domain = domain if rr == "@" else f"{rr}.{domain}"

    data = _aliyun_request(config, "DescribeSubDomainRecords", {
        "SubDomain": sub_domain,
        "Type": "A",
        "PageSize": 20
    })
    records = data.get("DomainRecords", {}).get("Record", [])
    if isinstance(records, dict):
        records = [records]
    target = next((r for r in records if str(r.get("Type", "")).upper() == "A"), None)

    if target and target.get("Value") == new_ip:
        print("当前 IP 已是最优，无需更新。")
        return "NO_CHANGE"

    if target:
        _aliyun_request(config, "UpdateDomainRecord", {
            "RecordId": target["RecordId"],
            "RR": rr,
            "Type": "A",
            "Value": new_ip,
            "TTL": ttl
        })
    else:
        _aliyun_request(config, "AddDomainRecord", {
            "DomainName": domain,
            "RR": rr,
            "Type": "A",
            "Value": new_ip,
            "TTL": ttl
        })
    print("DNS 更新成功！")
    return True


def _aws_sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _aws_v4_headers(method, service, region, host, canonical_uri, canonical_query, payload, access_key, secret_key, session_token=""):
    now = datetime.datetime.utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    headers = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date
    }
    if session_token:
        headers["x-amz-security-token"] = session_token

    sorted_header_items = sorted(headers.items(), key=lambda x: x[0])
    canonical_headers = "".join(f"{k}:{v}\n" for k, v in sorted_header_items)
    signed_headers = ";".join(k for k, _ in sorted_header_items)
    canonical_request = (
        f"{method}\n{canonical_uri}\n{canonical_query}\n"
        f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )

    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = (
        "AWS4-HMAC-SHA256\n"
        f"{amz_date}\n"
        f"{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )
    signing_key = _aws_sign(_aws_sign(_aws_sign(_aws_sign(("AWS4" + secret_key).encode("utf-8"), date_stamp), region), service), "aws4_request")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        "AWS4-HMAC-SHA256 "
        f"Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    req_headers = {
        "Authorization": authorization,
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash
    }
    if session_token:
        req_headers["x-amz-security-token"] = session_token
    return req_headers


def _route53_request(config, method, uri, query="", body=""):
    dns_cfg = config.get("dns", {}).get("route53", {})
    access_key = _dns_required(dns_cfg, "access_key_id", "route53")
    secret_key = _dns_required(dns_cfg, "secret_access_key", "route53")
    session_token = str(dns_cfg.get("session_token", "")).strip()
    service = "route53"
    region = "us-east-1"
    host = "route53.amazonaws.com"
    headers = _aws_v4_headers(method, service, region, host, uri, query, body, access_key, secret_key, session_token=session_token)
    url = f"https://{host}{uri}"
    if query:
        url = f"{url}?{query}"
    resp = requests.request(method, url, data=body.encode("utf-8"), headers=headers, timeout=20)
    resp.raise_for_status()
    return resp


def get_current_dns_ip_route53(config):
    dns_cfg = config.get("dns", {}).get("route53", {})
    hosted_zone_id = str(_dns_required(dns_cfg, "hosted_zone_id", "route53")).replace("/hostedzone/", "").strip()
    record_name = _ensure_fqdn(_dns_required(dns_cfg, "record_name", "route53"))
    uri = f"/2013-04-01/hostedzone/{hosted_zone_id}/rrset"
    query = f"name={quote(record_name, safe='')}&type=A&maxitems=1"
    resp = _route53_request(config, "GET", uri, query=query, body="")
    root = ET.fromstring(resp.text)
    ns = {"r": "https://route53.amazonaws.com/doc/2013-04-01/"}
    rrsets = root.findall(".//r:ResourceRecordSet", ns)
    for rr in rrsets:
        name = (rr.findtext("r:Name", default="", namespaces=ns) or "").strip()
        rr_type = (rr.findtext("r:Type", default="", namespaces=ns) or "").strip().upper()
        if rr_type == "A" and name.rstrip(".") == record_name.rstrip("."):
            values = rr.findall("r:ResourceRecords/r:ResourceRecord/r:Value", ns)
            if values:
                return (values[0].text or "").strip()
    return None


def update_dns_route53(config, new_ip):
    dns_cfg = config.get("dns", {}).get("route53", {})
    hosted_zone_id = str(_dns_required(dns_cfg, "hosted_zone_id", "route53")).replace("/hostedzone/", "").strip()
    record_name = _ensure_fqdn(_dns_required(dns_cfg, "record_name", "route53"))
    ttl = _safe_int(dns_cfg.get("ttl", 60), 60, min_value=1)
    current_ip = get_current_dns_ip_route53(config)
    if current_ip == new_ip:
        print("当前 IP 已是最优，无需更新。")
        return "NO_CHANGE"

    change_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ChangeResourceRecordSetsRequest xmlns="https://route53.amazonaws.com/doc/2013-04-01/">'
        "<ChangeBatch>"
        "<Changes><Change><Action>UPSERT</Action><ResourceRecordSet>"
        f"<Name>{record_name}</Name><Type>A</Type><TTL>{ttl}</TTL>"
        f"<ResourceRecords><ResourceRecord><Value>{new_ip}</Value></ResourceRecord></ResourceRecords>"
        "</ResourceRecordSet></Change></Changes>"
        "</ChangeBatch>"
        "</ChangeResourceRecordSetsRequest>"
    )
    uri = f"/2013-04-01/hostedzone/{hosted_zone_id}/rrset"
    _route53_request(config, "POST", uri, query="", body=change_xml)
    print("DNS 更新成功！")
    return True


def _huawei_headers(config):
    dns_cfg = config.get("dns", {}).get("huawei", {})
    token = _dns_required(dns_cfg, "token", "huawei")
    return {
        "X-Auth-Token": token,
        "Content-Type": "application/json"
    }


def _huawei_base_url(config):
    dns_cfg = config.get("dns", {}).get("huawei", {})
    return str(dns_cfg.get("base_url", "https://dns.myhuaweicloud.com")).rstrip("/")


def get_current_dns_ip_huawei(config):
    dns_cfg = config.get("dns", {}).get("huawei", {})
    zone_id = _dns_required(dns_cfg, "zone_id", "huawei")
    record_name = _ensure_fqdn(_dns_required(dns_cfg, "record_name", "huawei"))
    url = f"{_huawei_base_url(config)}/v2/zones/{zone_id}/recordsets"
    params = {"name": record_name, "type": "A"}
    resp = requests.get(url, headers=_huawei_headers(config), params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    records = data.get("recordsets", []) or []
    if records and records[0].get("records"):
        return str(records[0]["records"][0]).strip()
    return None


def update_dns_huawei(config, new_ip):
    dns_cfg = config.get("dns", {}).get("huawei", {})
    zone_id = _dns_required(dns_cfg, "zone_id", "huawei")
    record_name = _ensure_fqdn(_dns_required(dns_cfg, "record_name", "huawei"))
    ttl = _safe_int(dns_cfg.get("ttl", 60), 60, min_value=1)
    base_url = _huawei_base_url(config)
    headers = _huawei_headers(config)
    list_url = f"{base_url}/v2/zones/{zone_id}/recordsets"
    params = {"name": record_name, "type": "A"}
    list_resp = requests.get(list_url, headers=headers, params=params, timeout=15)
    list_resp.raise_for_status()
    records = list_resp.json().get("recordsets", []) or []

    if records and records[0].get("records"):
        current_ip = str(records[0]["records"][0]).strip()
        if current_ip == new_ip:
            print("当前 IP 已是最优，无需更新。")
            return "NO_CHANGE"
        record_id = records[0]["id"]
        put_url = f"{base_url}/v2/zones/{zone_id}/recordsets/{record_id}"
        payload = {
            "name": record_name,
            "description": records[0].get("description", ""),
            "type": "A",
            "ttl": ttl,
            "records": [new_ip]
        }
        put_resp = requests.put(put_url, headers=headers, json=payload, timeout=15)
        put_resp.raise_for_status()
    else:
        payload = {
            "name": record_name,
            "type": "A",
            "ttl": ttl,
            "records": [new_ip]
        }
        create_resp = requests.post(list_url, headers=headers, json=payload, timeout=15)
        create_resp.raise_for_status()
    print("DNS 更新成功！")
    return True


def _gcp_headers(config):
    dns_cfg = config.get("dns", {}).get("gcp", {})
    access_token = _dns_required(dns_cfg, "access_token", "gcp")
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}


def get_current_dns_ip_gcp(config):
    dns_cfg = config.get("dns", {}).get("gcp", {})
    project_id = _dns_required(dns_cfg, "project_id", "gcp")
    managed_zone = _dns_required(dns_cfg, "managed_zone", "gcp")
    record_name = _ensure_fqdn(_dns_required(dns_cfg, "record_name", "gcp"))
    url = f"https://dns.googleapis.com/dns/v1/projects/{project_id}/managedZones/{managed_zone}/rrsets"
    params = {"name": record_name, "type": "A"}
    resp = requests.get(url, headers=_gcp_headers(config), params=params, timeout=15)
    resp.raise_for_status()
    rrsets = resp.json().get("rrsets", []) or []
    if rrsets and rrsets[0].get("rrdatas"):
        return str(rrsets[0]["rrdatas"][0]).strip()
    return None


def update_dns_gcp(config, new_ip):
    dns_cfg = config.get("dns", {}).get("gcp", {})
    project_id = _dns_required(dns_cfg, "project_id", "gcp")
    managed_zone = _dns_required(dns_cfg, "managed_zone", "gcp")
    record_name = _ensure_fqdn(_dns_required(dns_cfg, "record_name", "gcp"))
    ttl = _safe_int(dns_cfg.get("ttl", 60), 60, min_value=1)
    base = f"https://dns.googleapis.com/dns/v1/projects/{project_id}/managedZones/{managed_zone}"
    rr_url = f"{base}/rrsets"
    params = {"name": record_name, "type": "A"}
    list_resp = requests.get(rr_url, headers=_gcp_headers(config), params=params, timeout=15)
    list_resp.raise_for_status()
    rrsets = list_resp.json().get("rrsets", []) or []
    current = rrsets[0] if rrsets else None
    if current and current.get("rrdatas") and str(current["rrdatas"][0]).strip() == new_ip:
        print("当前 IP 已是最优，无需更新。")
        return "NO_CHANGE"

    additions = [{"name": record_name, "type": "A", "ttl": ttl, "rrdatas": [new_ip]}]
    payload = {"additions": additions}
    if current:
        payload["deletions"] = [current]
    change_url = f"{base}/changes"
    ch_resp = requests.post(change_url, headers=_gcp_headers(config), json=payload, timeout=15)
    ch_resp.raise_for_status()
    print("DNS 更新成功！")
    return True


def _azure_headers(config):
    dns_cfg = config.get("dns", {}).get("azure", {})
    token = _dns_required(dns_cfg, "access_token", "azure")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _azure_record_url(config):
    dns_cfg = config.get("dns", {}).get("azure", {})
    subscription_id = _dns_required(dns_cfg, "subscription_id", "azure")
    resource_group = _dns_required(dns_cfg, "resource_group", "azure")
    zone_name = _dns_required(dns_cfg, "zone_name", "azure")
    record_name = str(_dns_required(dns_cfg, "record_name", "azure")).strip()
    api_version = str(dns_cfg.get("api_version", "2018-05-01")).strip()
    return (
        "https://management.azure.com/"
        f"subscriptions/{subscription_id}/resourceGroups/{resource_group}/"
        f"providers/Microsoft.Network/dnsZones/{zone_name}/A/{record_name}"
        f"?api-version={api_version}"
    )


def get_current_dns_ip_azure(config):
    url = _azure_record_url(config)
    resp = requests.get(url, headers=_azure_headers(config), timeout=15)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    records = data.get("properties", {}).get("aRecords", [])
    if records and records[0].get("ipv4Address"):
        return str(records[0]["ipv4Address"]).strip()
    return None


def update_dns_azure(config, new_ip):
    dns_cfg = config.get("dns", {}).get("azure", {})
    ttl = _safe_int(dns_cfg.get("ttl", 60), 60, min_value=1)
    current_ip = get_current_dns_ip_azure(config)
    if current_ip == new_ip:
        print("当前 IP 已是最优，无需更新。")
        return "NO_CHANGE"
    url = _azure_record_url(config)
    payload = {
        "properties": {
            "TTL": ttl,
            "aRecords": [{"ipv4Address": new_ip}]
        }
    }
    resp = requests.put(url, headers=_azure_headers(config), json=payload, timeout=15)
    resp.raise_for_status()
    print("DNS 更新成功！")
    return True


def get_current_dns_ip(config):
    provider = _get_dns_provider(config)
    if provider == "cloudflare":
        return get_current_dns_ip_cloudflare(config)
    if provider == "dnspod":
        return get_current_dns_ip_dnspod(config)
    if provider == "aliyun":
        return get_current_dns_ip_aliyun(config)
    if provider == "route53":
        return get_current_dns_ip_route53(config)
    if provider == "huawei":
        return get_current_dns_ip_huawei(config)
    if provider == "gcp":
        return get_current_dns_ip_gcp(config)
    if provider == "azure":
        return get_current_dns_ip_azure(config)
    raise ValueError(f"不支持的DNS服务商: {provider}")


def update_dns_record(config, new_ip):
    provider = _get_dns_provider(config)
    print(f"当前 DNS 服务商: {_provider_name(provider)}")
    if provider == "cloudflare":
        return update_dns_cloudflare(config, new_ip)
    if provider == "dnspod":
        return update_dns_dnspod(config, new_ip)
    if provider == "aliyun":
        return update_dns_aliyun(config, new_ip)
    if provider == "route53":
        return update_dns_route53(config, new_ip)
    if provider == "huawei":
        return update_dns_huawei(config, new_ip)
    if provider == "gcp":
        return update_dns_gcp(config, new_ip)
    if provider == "azure":
        return update_dns_azure(config, new_ip)
    raise ValueError(f"不支持的DNS服务商: {provider}")


# ============================================================
# Telegram 消息推送模块（并发多用户）
# ============================================================
def push_notification(config, message):
    """将结果通过 Telegram Bot 并发推送给一个或多个用户"""
    tg = config.get("telegram", {})
    token = str(tg.get("bot_token", "")).strip()
    if not token:
        print("未配置 Telegram Bot Token，已跳过推送。")
        return

    chat_ids = _parse_telegram_chat_ids(tg.get("chat_id", ""))
    if not chat_ids:
        print("未配置 Telegram Chat ID，已跳过推送。")
        return

    def _send(chat_id):
        ok, _ = _send_telegram_message(
            config,
            chat_id,
            message,
            parse_mode="HTML",
            disable_web_page_preview=True,
            timeout=10
        )
        if ok:
            print(f"  ✓ 已推送至 {_mask_chat_id(chat_id)}")
        else:
            print(f"  ✗ 推送至 {_mask_chat_id(chat_id)} 失败")

    print("正在推送 Telegram 通知...")
    with ThreadPoolExecutor(max_workers=max(len(chat_ids), 1)) as executor:
        executor.map(_send, chat_ids)


# ============================================================
# 网络环境检测模块
# ============================================================
def check_network_environment():
    """检测当前网络是否处于翻墙状态，避免测速结果失真"""
    print("正在检测网络环境...")

    geo_timeout_sec = 2
    restricted_timeout_sec = 2
    ip = country = isp = "未知"
    country_code = ""
    non_cn_hit = None
    restricted_reachable = False

    def _fetch_ipinfo_io():
        r = requests.get("https://ipinfo.io/json", timeout=geo_timeout_sec)
        r.raise_for_status()
        d = r.json()
        return (
            d.get("ip", "未知"),
            d.get("country", ""),
            d.get("country", "未知"),
            d.get("org", "未知"),
        )

    def _fetch_ipapi():
        r = requests.get("http://ip-api.com/json/?fields=query,country,countryCode,isp", timeout=geo_timeout_sec)
        r.raise_for_status()
        d = r.json()
        return (
            d.get("query", "未知"),
            d.get("countryCode", ""),
            d.get("country", "未知"),
            d.get("isp", "未知"),
        )

    def _probe_restricted(url):
        r = requests.head(url, timeout=restricted_timeout_sec, allow_redirects=False)
        if r.status_code == 405:
            r = requests.get(url, timeout=restricted_timeout_sec, allow_redirects=False)
        return r.status_code < 400

    with ThreadPoolExecutor(max_workers=4) as executor:
        geo_futures = [
            executor.submit(_fetch_ipinfo_io),
            executor.submit(_fetch_ipapi),
        ]
        for future in as_completed(geo_futures):
            try:
                _ip, _country_code, _country, _isp = future.result()
            except Exception:
                continue
            if _ip and _ip != "未知" and ip == "未知":
                ip, country_code, country, isp = _ip, _country_code, _country, _isp
            if _country_code and _country_code != "CN" and non_cn_hit is None:
                non_cn_hit = (_country or "未知", _country_code)

        probe_futures = [
            executor.submit(_probe_restricted, "https://www.google.com/generate_204"),
        ]
        for future in as_completed(probe_futures):
            try:
                ok = future.result()
            except Exception:
                continue
            if ok:
                restricted_reachable = True
                break

    if ip != "未知":
        print(f"当前出口 IP: {ip} | 地区: {country} | ISP: {isp}")
    else:
        print("警告: 无法获取出口 IP 信息。")

    if non_cn_hit is not None:
        hit_country, _ = non_cn_hit
        print(f"\n❌ 检测到出口 IP 位于 [{hit_country}]，当前处于翻墙状态！")
        print("   Cloudflare 优选测速需要在纯国内网络下进行，结果才有意义。")
        print("   请关闭代理 / VPN 后重新运行。")
        _exit_with_pause()

    if restricted_reachable:
        print("\n⚠️ 检测到受限站点可直连。")
        print("   当前出口地区为 CN，该信号可能由运营商网络策略导致，不强制拦截。")
        print("   若测速结果异常，请手动确认已关闭代理 / VPN。")
        print("✅ 网络环境检测已通过，继续执行。\n")
        return

    print("✅ 网络环境正常（未检测到翻墙），继续执行。\n")


def show_help_menu():
    print("\n================ 帮助 ================")
    print("【主菜单说明】")
    print("1、快速获取优选IP：")
    print("   适用于没有域名的场景，仅测速并输出推荐IP，不执行DNS更新。")
    print("2、获取优选IP动态更新DNS：")
    print("   适用于已有域名场景，支持Cloudflare/DNSPod/阿里云/Route53/华为云/GCP/Azure。")
    print("3、系统设置：")
    print("   配置Telegram推送、自定义优选IP汇聚源地址。")
    print("4、帮助：")
    print("   查看各模块和菜单功能说明。")
    print("5、退出：")
    print("   结束程序。")
    print("")
    print("【动态更新DNS流程说明】")
    print("1、先进入“新增/修改/删除 待更新域名配置”，维护域名与服务商凭据。")
    print("2、选择官方源或自定义源拉取IP。")
    print("3、系统执行多轮测速，每轮保留最优候选。")
    print("4、确认后将候选最优IP更新到目标DNS记录。")
    print("")
    print("【系统设置说明】")
    print("- Telegram Bot推送：用于接收测速结果和DNS更新结果。")
    print("- 自定义优选IP源地址：用于接入你私有化部署的IP汇聚接口。")
    print("======================================\n")


# ============================================================
# 主执行流程
# ============================================================
def main():
    # 1. 加载配置
    config = load_config()
    settings = config.setdefault('settings', {})

    # 用户选择模式
    need_dns_record_check = False
    enable_dns_update = False
    while True:
        need_dns_record_check = False
        print("请选择模式（默认 2）：")
        print("1、快速获取优选IP（没有域名，仅需系统快速测速提供优选IP）")
        print("2、获取优选IP动态更新DNS （已有域名，支持多DNS服务商）")
        print("3、系统设置（设置Telegram Bot推送、自定义优选IP源地址）")
        print("4、帮助")
        print("5、退出")
        choice = input("> ").strip()
        if not choice:
            choice = '2'
        if choice == '1':
            enable_dns_update = False
            print("已选择快速测速模式，将仅提供优选IP，不更新域名。")
            settings["_runtime_custom_source_no_auth"] = False
            settings["_runtime_source_urls"] = [_get_official_ip_source_url(settings)]
            break
        if choice == '2':
            while True:
                profiles = _ensure_dns_profiles(config)
                if profiles:
                    break
                print("未检测到待更新域名配置，进入引导新增流程。")
                if _create_dns_profile(config):
                    break
                print("配置验证未通过，请按提示重新配置。")

            while True:
                print("\n请选择操作（默认 2）：")
                print("1、新增/修改/删除 待更新域名配置")
                print("2、使用软件官方源进行测速并更新域名解析")
                print("3、自定义优选IP源进行测速并更新域名解析")

                sub_choice = input("> ").strip()
                if not sub_choice:
                    sub_choice = "2"

                if sub_choice == "1":
                    manage_dns_profiles(config)
                    continue

                if sub_choice not in ("2", "3"):
                    print("无效选择，请重试。")
                    continue

                selected_profile = _select_dns_profile(
                    config,
                    prompt_text="请选择用于本次更新的域名配置序号",
                    allow_back=True,
                )
                if not selected_profile:
                    print("已返回上层菜单。")
                    continue

                missing = _dns_profile_missing_fields(selected_profile)
                if missing:
                    print(f"所选配置不完整，缺少字段: {', '.join(missing)}")
                    print("请先选择 1 进行修改完善。")
                    continue

                _apply_dns_profile_to_runtime_config(config, selected_profile)

                need_dns_record_check = True
                if sub_choice == "2":
                    print("已选择官方源进行测速并更新域名。")
                    settings["_runtime_custom_source_no_auth"] = False
                    settings["_runtime_source_urls"] = [_get_official_ip_source_url(settings)]
                else:
                    print("请确保已经fork https://github.com/wzlinbin/CloudFlareIP-RenewDNS 并按指引自建好有效IP聚合源")
                    custom_url = configure_custom_ip_source(
                        config,
                        allow_blank_use_existing=True,
                        allow_back=True,
                    )
                    if not custom_url:
                        print("已返回上层菜单。")
                        continue
                    settings["_runtime_custom_source_no_auth"] = True
                    settings["_runtime_source_urls"] = [custom_url]
                    print("自建源模式已启用：将直接读取该 IP 源，不附带任何鉴权头。")

                enable_dns_update = True
                break
            if enable_dns_update:
                break
            continue
        if choice == '3':
            manage_system_settings(config)
            continue
        if choice == '4':
            show_help_menu()
            continue
        if choice == '5':
            print("已退出。")
            return
        print("无效选择，请重试。")

    max_retries = _safe_int(settings.get('max_retries', 3), 3, min_value=1)

    # 2. 网络检测（主线程，翻墙状态下暂停后退出）
    check_network_environment()

    # 3. 获取当前 DNS IP（仅开启 DNS 更新时）
    current_ip = None
    if enable_dns_update:
        try:
            current_ip = get_current_dns_ip(config)
            dns_target_label = _get_dns_target_label(config)
            provider_name = _provider_name(_get_dns_provider(config))
            if need_dns_record_check:
                if not current_ip:
                    print(
                        f"错误: 未在 {provider_name} 中找到 {dns_target_label} 的解析记录。"
                        "请先创建 A 记录后再执行测速更新。"
                    )
                    return
                print(f"已检测到 DNS 记录: {dns_target_label} -> {current_ip}")
        except Exception as e:
            print("DNS 记录检查失败，请检查网络与配置后重试。")
            return

    # 4. 多轮测速：每轮保留该轮最优结果作为候选
    history = []   # [(轮次, ip, speed, region, speed_val), ...]
    ip_pool_loaded = False

    round_num = 0
    while True:
        round_num += 1
        print(f"\n🔄 第 {round_num} 轮测速开始...")

        best_ip = speed = region = None
        speed_val = 0.0

        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                print(f"⚠️  第 {attempt}/{max_retries} 次重试，重新测速...")

            if not ip_pool_loaded:
                if not fetch_ips(config, current_ip):
                    print("停止运行：IP 库加载失败。")
                    return
                ip_pool_loaded = True
            else:
                print("IP源刷新频率：60分钟，不重新请求后端 IP 源。")

            best_ip, speed, region = run_speed_test(config)
            try:
                speed_val = float(speed) if speed is not None else 0.0
            except (ValueError, TypeError):
                speed_val = 0.0

            if best_ip and speed_val > 0:
                break

            if attempt < max_retries:
                print("⚠️  本次测速下载速度为 0，继续重试...")

        if best_ip and speed_val > 0:
            history.append((round_num, best_ip, speed, region, speed_val))
            print(f"✅ 第 {round_num} 轮最优: {best_ip} | {region} | {speed} MB/s（已加入候选）")
        else:
            print(f"❌ 第 {round_num} 轮未得到有效结果，跳过该轮。")
        
        if history:
            sorted_history = sorted(history, key=lambda x: x[4], reverse=True)
            print(f"\n{'='*56}")
            print("当前候选池（每轮最优，按速度排序）:")
            for i, (rnd, h_ip, h_spd, h_reg, _) in enumerate(sorted_history, start=1):
                tag = "  <- 当前推荐" if i == 1 else ""
                print(f"  [{i}] 第 {rnd} 轮  {h_ip} | {h_reg} | {h_spd} MB/s{tag}")
            print(f"{'='*56}")
            print("操作：R=继续下一轮测速  回车/Y=进入结果处理")
            try:
                next_action = input("> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                next_action = ''
            if next_action == 'r':
                continue

            if enable_dns_update:
                _, sel_ip, sel_spd, sel_reg, _ = sorted_history[0]
                print(f"当前最优推荐: {sel_ip} | {sel_reg} | {sel_spd} MB/s")
                dns_target_label = _get_dns_target_label(config)
                print(f"确认使用最优推荐更新 {dns_target_label}？（回车/Y=确认，R=继续测速）")
                try:
                    final_action = input("> ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    final_action = 'r'

                if final_action == 'r':
                    continue
                if final_action not in ('y', ''):
                    print("已取消本次更新，继续测速。")
                    continue

                try:
                    update_status = update_dns_record(config, sel_ip)
                except Exception:
                    print("DNS 更新失败，请检查网络与配置后重试。")
                    continue
                if update_status is True:
                    msg = (f"✅ <b>DNS 优选 IP 更新成功</b>\n"
                           f"<b>域名:</b> <code>{_escape_html(_get_dns_target_label(config))}</code>\n"
                           f"<b>解析 IP:</b> <code>{_escape_html(sel_ip)}</code>\n"
                           f"<b>地区码:</b> <b>{_escape_html(sel_reg)}</b>\n"
                           f"<b>实测速度:</b> <b>{_escape_html(sel_spd)} MB/s</b>")
                    push_notification(config, _append_ack_to_push_message(msg))
                elif update_status == "NO_CHANGE":
                    print("状态: 当前 IP 已是最优，无需更新。")
                else:
                    msg = (f"❌ <b>DNS 优选 IP 更新失败</b>\n"
                           f"<b>最优 IP:</b> <code>{_escape_html(sel_ip)}</code>\n"
                           "原因: API 调用报错，请检查日志或令牌权限。")
                    push_notification(config, _append_ack_to_push_message(msg))
                _exit_with_pause(0)
                return

            _, best_ip, best_spd, best_reg, _ = sorted_history[0]
            print("状态: DNS 自动更新已禁用，仅输出多轮候选与推荐结果。")
            msg = (f"💡 <b>CF 优选 IP 测速完成</b>\n"
                   f"<b>推荐 IP:</b> <code>{_escape_html(best_ip)}</code>\n"
                   f"<b>地区码:</b> <b>{_escape_html(best_reg)}</b>\n"
                   f"<b>实测速度:</b> <b>{_escape_html(best_spd)} MB/s</b>\n"
                   "<i>(已完成多轮测速，每轮最优均已作为候选)</i>")
            push_notification(config, _append_ack_to_push_message(msg))
            _exit_with_pause(0)
            return

        print("当前暂无有效候选。操作：R=继续重测  其他键=结束")
        try:
            next_action = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            next_action = ''
        if next_action == 'r':
            continue
        print("未产生可用候选，程序结束。")
        return


if __name__ == "__main__":
    main()
