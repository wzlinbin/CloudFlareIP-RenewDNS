import requests
import re
import os
import json
import subprocess
import csv
import sys
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

    base_url = config.get('cloudflare', {}).get('base_url', config.get('telegram', {}).get('base_url', 'https://api.cloudflare.com')).rstrip('/')
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
    source_url = settings.get('ip_api_url') or "http://tgbot.xiaoliu.sbs/all"
    timeout = _safe_int(settings.get('timeout', 15), 15, min_value=1)
    default_auth = "oieGutOR5QgV7Xx2d7N47ajbZFRsTwuk"
    auth_key = settings.get('auth_key') or config.get('telegram', {}).get('auth_key', '') or default_auth
    headers = {"x-auth-key": auth_key} if auth_key else {}
    ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
    all_ips = set()

    if current_ip:
        all_ips.add(current_ip)
        print(f"已将当前解析 IP {current_ip} 加入测速池进行对比。")

    try:
        print(f"正在从接口获取 IP 数据: {source_url}")
        resp = requests.get(source_url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        api_ips = re.findall(ip_pattern, resp.text)
        all_ips.update(api_ips)
        print(f"接口返回 {len(api_ips)} 条 IPv4，去重后共 {len(all_ips)} 条待测速。")
    except Exception as e:
        print(f"错误: 从 {source_url} 获取 IP 失败: {e}")
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
    base_url     = config['telegram'].get('base_url', 'https://api.telegram.org').rstrip('/')
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

    enable_dns_update = config.get('settings', {}).get('enable_dns_update', True)
    max_retries       = _safe_int(config.get('settings', {}).get('max_retries', 3), 3, min_value=1)

    # 2. 网络检测（主线程，翻墙状态下暂停后退出）
    check_network_environment()

    # 3. 获取当前 DNS IP（仅开启 DNS 更新时）
    current_ip = get_current_dns_ip(config) if enable_dns_update else None

    # 4. 测速 + 确认循环（用户按 R 可重新测速，历史结果可随时选用）
    history   = []   # [(轮次, ip, speed, region), ...]
    round_num = 0

    while True:
        round_num += 1
        if round_num > 1:
            print(f"\n🔄 第 {round_num} 次测速开始...\n")

        # ── 速度为 0 自动重试 ──────────────────────────────────
        best_ip = speed = region = None
        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                print(f"\n⚠️  第 {attempt}/{max_retries} 次重试，重新抓取 IP 并测速...")

            if not fetch_ips(config, current_ip):
                print("停止运行：IP 库加载失败。")
                return

            best_ip, speed, region = run_speed_test(config)

            try:
                speed_val = float(speed) if speed is not None else 0.0
            except (ValueError, TypeError):
                speed_val = 0.0

            if best_ip and speed_val > 0:
                break

            if attempt < max_retries:
                print(f"⚠️  测速结果下载速度为 0，可能是网络抖动，即将自动重试...")
            else:
                print(f"❌ 已重试 {max_retries} 次，下载速度仍为 0，请检查网络后手动重新运行。")
                return

        if not best_ip:
            print("未能定位到任何有效的最优 IP。")
            return

        # ── 本轮结果加入历史 ───────────────────────────────────
        history.append((round_num, best_ip, speed, region, speed_val))

        if enable_dns_update:
            sorted_history = sorted(history, key=lambda x: x[4], reverse=True)

            # 显示按速度排序后的历史结果，回车默认使用全历史最快结果
            while True:
                print(f"\n{'='*48}")
                print("  历史测速结果（按速度排序）:")
                for i, (rnd, h_ip, h_spd, h_reg, _) in enumerate(sorted_history, start=1):
                    tag = "  <- 默认推荐" if i == 1 else ""
                    print(f"    [{i}] 第 {rnd} 次  {h_ip} | {h_reg} | {h_spd} MB/s{tag}")
                print(f"{'='*48}")

                hint = f"回车/Y=使用默认推荐(最快)  1~{len(sorted_history)}=选择历史结果  R=重新测速"
                print(f"操作：{hint}")

                try:
                    answer = input("> ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    answer = 'r'

                if answer in ('y', ''):
                    _, sel_ip, sel_spd, sel_reg, _ = sorted_history[0]
                    break
                elif answer == 'r':
                    print("\n🔄 正在重新开始测速...\n")
                    break
                elif answer.isdigit() and 1 <= int(answer) <= len(sorted_history):
                    idx = int(answer)
                    _, sel_ip, sel_spd, sel_reg, _ = sorted_history[idx - 1]
                    print(f"✅ 已选择第 {idx} 项结果: {sel_ip} | {sel_reg} | {sel_spd} MB/s")
                    break
                else:
                    print("无效输入，请重试。")
                    continue

            if answer == 'r':
                continue  # 回到 while True 重新测速
            update_status = update_cf_dns(config, sel_ip)
            if update_status is True:
                msg = (f"✅ <b>CF 优选 IP 更新成功</b>\n"
                       f"域名: <code>{config['cloudflare']['dns_name']}</code>\n"
                       f"解析 IP: <b>{sel_ip}</b>\n"
                       f"地区码: <b>{sel_reg}</b>\n"
                       f"实测速度: <b>{sel_spd} MB/s</b>")
                push_notification(config, msg)
            elif update_status == "NO_CHANGE":
                print("状态: 当前 IP 已是最优，无需更新。")
            else:
                msg = (f"❌ <b>CF 优选 IP 更新失败</b>\n"
                       f"最优 IP: {sel_ip}\n"
                       f"原因: API 调用报错，请检查日志或令牌权限。")
                push_notification(config, msg)
            break  # 更新完成，退出大循环
        else:
            print("状态: DNS 自动更新已禁用，仅推送优选结果。")
            msg = (f"💡 <b>CF 优选 IP 测速完成</b>\n"
                   f"最优 IP: <b>{best_ip}</b>\n"
                   f"地区码: <b>{region}</b>\n"
                   f"实测速度: <b>{speed} MB/s</b>\n"
                   f"<i>(提示：由于禁用了自动更新域名，请手动修改您的优选信息。)</i>")
            push_notification(config, msg)
            break  # 无需确认，直接结束

    _exit_with_pause(0)


if __name__ == "__main__":
    main()



