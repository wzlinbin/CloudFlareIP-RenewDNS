# CloudFlareIP-RenewDNS 🚀

自动获取 Cloudflare 优选 IP，支持多轮测速，并按结果自动更新多家 DNS 服务商记录。

## ✨ 功能特性

- 优选 IP 拉取与去重：从官方或自定义 IP 汇聚源获取 IPv4。
- 多轮测速：每轮保留最优结果，形成候选池，支持继续测速或退出。
- DNS 自动更新：支持以下服务商：
  - Cloudflare
  - DNSPod
  - 阿里云 DNS
  - AWS Route53
  - 华为云 DNS
  - Google Cloud DNS
  - Azure DNS
- Telegram 推送：
  - 可在系统设置中配置 Bot Token / Chat ID。
  - 配置完成后会自动发送验证消息。
  - 测速/更新结果可自动推送。
- Worker 聚合与代理：
  - `cfworker.js` 提供聚合接口（根路径 `/`）与 `/tg`、`/cf` 代理。
- 配置友好：
  - 首次运行若无 `config.json`，自动创建默认配置。

## 📁 项目结构

```text
.
├─ main.py                 # 主程序（测速、配置、DNS更新、TG推送）
├─ cfst.exe                # CloudflareSpeedTest 可执行文件
├─ cfworker.js             # Cloudflare Worker（聚合 + /tg + /cf 代理）
├─ cfwork-api-kv.js        # 高级版 Worker（可选）
├─ wrangler.toml           # Worker 部署配置
└─ .github/workflows/deploy.yml
```

## 🧩 运行环境

- Windows（推荐，已适配终端输出）
- Python 3.10+（建议 3.12）
- `requests` 库
- `cfst.exe` 放在项目根目录

安装依赖：

```bash
pip install requests
```

## ⚡ 快速开始

1. 克隆项目并进入目录。
2. 确认 `cfst.exe` 存在于项目根目录。
3. 运行：

```bash
python main.py
```

4. 首次运行会自动创建 `config.json`（若不存在）。
5. 按菜单选择：
   - `1` 仅测速拿优选 IP
   - `2` 测速并更新 DNS
   - `3` 系统设置（TG 推送、自定义 IP 源）
   - `4` 帮助
   - `5` 退出

## ⚙️ 配置说明（config.json）

程序会自动维护配置，常用字段如下：

- `settings.ip_api_url`: 官方 IP 源地址（默认 `https://cloudflareip.ocisg.xyz/api/data`）
- `settings.custom_ip_api_url`: 自定义 IP 源地址（可选）
- `settings.max_ips`: `cfst` 延迟测速并发参数（`-n`）
- `settings.top_n`: 下载测速候选数量（`-dn`）
- `settings.timeout`: 接口超时秒数
- `settings.max_retries`: 单轮测速失败重试次数
- `telegram.bot_token`: Telegram Bot Token
- `telegram.chat_id`: Telegram 用户/群 ID（多个用英文逗号）
- `dns_profiles`: 多 DNS 配置列表
- `settings.active_dns_profile_id`: 当前生效的 DNS 配置 ID

## 🔄 DNS 更新流程建议

1. 在 DNS 服务商面板先创建目标 `A` 记录。
2. 在程序中新增/修改域名配置并通过校验。
3. 选择官方或自定义 IP 源进行测速。
4. 确认使用最优结果后执行 DNS 更新。

## 📨 Telegram 推送说明

- 在 `系统设置 -> 设置Telegram Bot推送` 中填写 Token 和 Chat ID。
- 配置保存后会自动发送一条测试消息做有效性验证。
- 发送失败时会提示常见原因（Token/Chat ID/会话未启动/网络问题等）。

## 🔐 安全与注意事项

- 不要把包含密钥的配置文件提交到公开仓库。
- 测速前建议关闭代理/VPN，避免结果失真。
- 自定义 IP 源请确保可访问且返回有效 IPv4 数据。
- 若提示“未找到 A 记录”，请先在 DNS 控制台创建记录。
- 若提示“凭据无效或权限不足”，请检查 Token/Key 权限与资源范围。

## ☁️ Worker 部署（cfworker.js）

Worker 的完整部署说明见：

- [docs/WORKER_DEPLOY.md](docs/WORKER_DEPLOY.md)

## 🙏 致谢

- 本项目：<https://github.com/wzlinbin/CloudFlareIP-RenewDNS>
- 测速能力来源：<https://github.com/XIU2/CloudflareSpeedTest>
- 讨论 TG：<https://t.me/iprenewdns>
