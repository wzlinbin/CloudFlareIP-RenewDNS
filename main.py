
import requests
import re
import os
import json
import subprocess
import csv
import sys
import hashlib
import hmac
import time
import secrets
import platform
import uuid
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# Windows 终端强制 UTF-8 输出，避免 emoji / 中文字符编码错误
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def _exit_with_pause(code=1):
    """报错退出前暂停，防止窗口一闪而过"""
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


DEFAULT_WORKER_BASE_URL = "https://cloudflareip.ocisg.xyz"
DEFAULT_IP_SOURCE_URL = f"{DEFAULT_WORKER_BASE_URL}/api/data"


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

    admin_key = _get_admin_auth_key(config)
    if not admin_key:
        return None

    settings = config.get("settings", {})
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

    headers = {
        "x-auth-key": admin_key,
        "Content-Type": "application/json"
    }

    try:
        resp = requests.post(register_url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
        if not isinstance(body, dict) or body.get("ok") is not True:
            print(f"警告: 自动注册返回异常，回退到 admin-key。register={register_url}")
            return None
        return {
            "client_id": client_id,
            "client_secret": client_secret,
            "hwid": hwid
        }
    except Exception as e:
        print(f"警告: 自动注册一次性凭据失败，回退到 admin-key: {e}")
        return None


def _resolve_ip_source_urls(settings):
    urls = []
    ip_sources = settings.get("ip_sources")
    if isinstance(ip_sources, list):
        urls.extend([u.strip() for u in ip_sources if isinstance(u, str) and u.strip()])
    elif isinstance(ip_sources, str) and ip_sources.strip():
        urls.append(ip_sources.strip())

    single_url = settings.get("ip_api_url")
    if isinstance(single_url, str) and single_url.strip():
        urls.append(single_url.strip())

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
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.json')
    if not os.path.exists(config_path):
        config_path = 'config.json'
    if not os.path.exists(config_path):
        print(f"错误: 配置文件 {config_path} 不存在！")
        _exit_with_pause()
    with open(config_path, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


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

    base_url = config.get('cloudflare', {}).get('base_url', config.get('telegram', {}).get('base_url', DEFAULT_WORKER_BASE_URL)).rstrip('/')
    auth_key = config.get('cloudflare', {}).get('auth_key', config.get('telegram', {}).get('auth_key', ''))

    direct_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records{url_suffix}"
    
    # 尝试直连
    try:
        print(f"正在尝试直连 Cloudflare API...")
        res = requests.request(method, direct_url, headers=headers, timeout=10, **kwargs)
        if res.status_code == 200:
            return res
        print(f"直连失败 (状态码: {res.status_code})，准备切换代理...")
    except Exception as e:
        print(f"直连异常 ({e})，准备切换代理...")

    # 回退代理
    if "api.cloudflare.com" in base_url:
        return None
        
    proxy_headers = headers.copy()
    if auth_key:
        proxy_headers["x-auth-key"] = auth_key
    
    proxy_url = f"{base_url}/cf/client/v4/zones/{zone_id}/dns_records{url_suffix}"
    
    try:
        print(f"正在通过代理 {base_url} 访问 Cloudflare...")
        res = requests.request(method, proxy_url, headers=proxy_headers, timeout=15, **kwargs)
        return res
    except Exception as e:
        print(f"代理访问也失败了: {e}")
        return None


def get_current_dns_ip(config):
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
            print(f"正在从软件官方接口获取 IP 数据: {source_url} (auth={auth_mode})")
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
            print(f"错误: 从 {source_url} 获取 IP 失败: {e}")

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
def update_cf_dns(config, new_ip):
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


# ============================================================
# Telegram 消息推送模块（并发多用户）
# ============================================================
def push_notification(config, message):
    """将结果通过 Telegram Bot 并发推送给一个或多个用户"""
    token        = config['telegram']['bot_token']
    chat_ids     = [c.strip() for c in str(config['telegram']['chat_id']).split(',') if c.strip()]
    base_url     = config['telegram'].get('base_url', DEFAULT_WORKER_BASE_URL).rstrip('/')
    auth_key     = config['telegram'].get('auth_key', '')
    req_headers  = {"x-auth-key": auth_key} if auth_key else {}
    url          = f"{base_url}/tg/bot{token}/sendMessage"

    def _send(chat_id):
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        try:
            requests.post(url, headers=req_headers, json=payload, timeout=10)
            print(f"  ✓ 已推送至 {chat_id}")
        except Exception as e:
            print(f"  ✗ 推送至 {chat_id} 失败: {e}")

    print("正在推送 Telegram 通知...")
    with ThreadPoolExecutor(max_workers=max(len(chat_ids), 1)) as executor:
        executor.map(_send, chat_ids)


# ============================================================
# 网络环境检测模块
# ============================================================
def check_network_environment():
    """检测当前网络是否处于翻墙状态，避免测速结果失真"""
    print("正在检测网络环境...")

    ip = country = isp = '未知'
    country_code = ''

    def _fetch_ipinfo_io():
        r = requests.get("https://ipinfo.io/json", timeout=5)
        d = r.json()
        return (d.get('ip','未知'), d.get('country',''), d.get('country','未知'), d.get('org','未知'))

    def _fetch_ipapi():
        r = requests.get("http://ip-api.com/json/?fields=query,country,countryCode,isp", timeout=5)
        d = r.json()
        return (d.get('query','未知'), d.get('countryCode',''), d.get('country','未知'), d.get('isp','未知'))

    for fetch_fn in (_fetch_ipinfo_io, _fetch_ipapi):
        try:
            ip, country_code, country, isp = fetch_fn()
            if ip != '未知':
                break
        except Exception:
            continue
    else:
        print("警告: 无法获取出口 IP 信息，跳过地区检测。")
        country_code = 'CN'

    if ip != '未知':
        print(f"当前出口 IP: {ip} | 地区: {country} | ISP: {isp}")

    if country_code not in ('CN', ''):
        print(f"\n❌ 检测到出口 IP 位于 [{country}]，当前处于翻墙状态！")
        print("   Cloudflare 优选测速需要在纯国内网络下进行，结果才有意义。")
        print("   请关闭代理 / VPN 后重新运行。")
        _exit_with_pause()

    try:
        test = requests.get("https://www.google.com", timeout=4)
        if test.status_code < 400:
            print("\n❌ 检测到 Google 可直接访问，当前处于翻墙状态！")
            print("   请关闭代理 / VPN 后重新运行。")
            _exit_with_pause()
    except Exception:
        pass

    print("✅ 网络环境正常（未检测到翻墙），继续执行。\n")


# ============================================================
# 主执行流程
# ============================================================
def main():
    # 1. 加载配置
    config = load_config()

    # 用户选择模式
    print("请选择模式：")
    print("1. 快速测速提供优选IP")
    print("2. 已有CF托管域名，使用优选IP动态更新")
    choice = input("> ").strip()
    if choice == '1':
        enable_dns_update = False
        print("已选择快速测速模式，将仅提供优选IP，不更新域名。")
    elif choice == '2':
        print("请选择IP源：")
        print("A. 使用软件官方源进行测速并更新域名解析")
        print("B. 自建优选IP源进行测速并更新域名解析")
        sub_choice = input("> ").strip().upper()
        if sub_choice == 'A':
            print("已选择官方源进行测速并更新域名。")
        elif sub_choice == 'B':
            custom_url = input("请输入自建优选IP源URL: ").strip()
            if custom_url:
                config['settings']['ip_api_url'] = custom_url
                print(f"已设置自建源: {custom_url}")
            else:
                print("URL 为空，使用默认官方源。")
        else:
            print("无效选择，退出。")
            return
        enable_dns_update = True
    else:
        print("无效选择，退出。")
        return

    settings = config.get('settings', {})
    max_retries = _safe_int(settings.get('max_retries', 3), 3, min_value=1)

    # 2. 网络检测（主线程，翻墙状态下暂停后退出）
    # check_network_environment()  # 暂时关闭网络环境检测

    # 3. 获取当前 DNS IP（仅开启 DNS 更新时）
    current_ip = get_current_dns_ip(config) if enable_dns_update else None

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
                print("复用已缓存的 ip.txt，不重新请求后端 IP 源。")

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
            print("操作：R=继续下一轮测速  回车/Y=结束测速并进入候选选择")
            try:
                next_action = input("> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                next_action = ''
            if next_action == 'r':
                continue
            break

        print("当前暂无有效候选。操作：R=继续重测  其他键=结束")
        try:
            next_action = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            next_action = ''
        if next_action == 'r':
            continue
        print("未产生可用候选，程序结束。")
        return

    sorted_history = sorted(history, key=lambda x: x[4], reverse=True)

    if enable_dns_update:
        while True:
            hint = f"回车/Y=使用默认推荐(最快)  1~{len(sorted_history)}=选择候选"
            print(f"操作：{hint}")
            try:
                answer = input("> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = ''

            if answer in ('y', ''):
                _, sel_ip, sel_spd, sel_reg, _ = sorted_history[0]
                break
            if answer.isdigit() and 1 <= int(answer) <= len(sorted_history):
                idx = int(answer)
                _, sel_ip, sel_spd, sel_reg, _ = sorted_history[idx - 1]
                print(f"✅ 已选择第 {idx} 项候选: {sel_ip} | {sel_reg} | {sel_spd} MB/s")
                break
            print("无效输入，请重试。")

        update_status = update_cf_dns(config, sel_ip)
        if update_status is True:
            msg = (f"✅ <b>CF 优选 IP 更新成功</b>\n"
                   f"域名: <code>{config['cloudflare']['dns_name']}</code>\n"
                   f"解析 IP: <b>{sel_ip}</b>\n"
                   f"地区码: <b>{sel_reg}</b>\n"
                   f"实测速度: <b>{sel_spd} MB/s</b>")
            # push_notification(config, msg)  # 临时注释推送功能
        elif update_status == "NO_CHANGE":
            print("状态: 当前 IP 已是最优，无需更新。")
        else:
            msg = (f"❌ <b>CF 优选 IP 更新失败</b>\n"
                   f"最优 IP: {sel_ip}\n"
                   f"原因: API 调用报错，请检查日志或令牌权限。")
            # push_notification(config, msg)  # 临时注释推送功能
    else:
        _, best_ip, best_spd, best_reg, _ = sorted_history[0]
        print("状态: DNS 自动更新已禁用，仅输出多轮候选与推荐结果。")
        msg = (f"💡 <b>CF 优选 IP 测速完成</b>\n"
               f"推荐 IP: <b>{best_ip}</b>\n"
               f"地区码: <b>{best_reg}</b>\n"
               f"实测速度: <b>{best_spd} MB/s</b>\n"
               f"<i>(已完成多轮测速，每轮最优均已作为候选)</i>")
        # push_notification(config, msg)  # 临时注释推送功能

    _exit_with_pause(0)


if __name__ == "__main__":
    main()



