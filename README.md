# Optimal IP DNS Renewal Tool 🚀

自动获取 Cloudflare 优选 IP，支持多轮测速，并按结果自动更新多个 DNS 服务商解析记录。

## ✨ 功能特性

- 优选 IP 获取与去重（官方源 / 自定义源）
- 多轮测速，保留每轮最优作为候选
- DNS 自动更新（多服务商）
- Telegram 推送（配置后自动验证）
- 首次运行自动创建 `config.json`

支持的 DNS 服务商：

- Cloudflare
- DNSPod
- 阿里云 DNS
- AWS Route53
- 华为云 DNS
- Google Cloud DNS
- Azure DNS

## 📁 项目结构

```text
.
├─ main.py
├─ cfst.exe
├─ cfworker.js
├─ cfwork-api-kv.js          # 高级版（可选）
├─ docs/
│  └─ WORKER_DEPLOY.md
└─ .github/workflows/deploy.yml
```

## 🧩 运行环境

- Windows 10/11（推荐）
- Python 3.10+（建议 3.12）
- 依赖：`requests`

安装依赖：

```bash
pip install requests
```

## ⚡ Windows 直接运行说明

### 方式 A：直接运行 Python 脚本

```bash
python main.py
```

### 方式 B：运行打包好的单文件 EXE（推荐）

当前发布为 **Optimal IP DNS Renewal Tool.exe**，直接双击即可运行：

- `Optimal IP DNS Renewal Tool.exe`


> 说明：程序已将 `cfst.exe` 内嵌到单文件 EXE 内部。

首次运行若无 `config.json`，程序会自动生成默认配置文件。

## 🧭 使用流程

1. 进入系统设置，先配置 Telegram（可选但推荐）
2. 如需自动更新 DNS，先新增待更新域名配置
3. 选择官方源或自定义源开始测速
4. 查看候选池并确认更新

## 📨 Telegram Bot 申请与配置步骤

1. 在 Telegram 搜索 `@BotFather`
2. 发送 `/newbot`，按提示创建机器人
3. 获得 `Bot Token`（形如 `123456:ABC...`）
4. 给你的机器人先发送一次 `/start`
5. 获取你的 `Chat ID`：
   - 方式 1：使用 `@userinfobot`
6. 在程序菜单 `系统设置 -> 设置Telegram Bot推送` 填入 Token 和 Chat ID
7. 保存后程序会自动发送测试消息验证配置

## 🔑 各 DNS 服务商 API / Token 获取说明

### 1. Cloudflare

- 控制台路径：`My Profile -> API Tokens`
- 创建 Token，建议最小权限：
  - Zone:DNS:Edit
  - Zone:Zone:Read
- `Zone ID` 在域名 Overview 页面可查看

### 2. DNSPod（腾讯云）

- 控制台路径：腾讯云 `访问管理 CAM -> API密钥管理`
- 获取 `SecretId` / `SecretKey`
- 需要提供主域名 `domain` 和主机记录 `sub_domain`

### 3. 阿里云 DNS

- 控制台路径：阿里云 `RAM -> AccessKey`
- 建议创建子账号并授予 DNS 最小权限
- 获取 `AccessKeyId` / `AccessKeySecret`

### 4. AWS Route53

- 控制台路径：AWS `IAM -> Users -> Security credentials`
- 获取 `Access key ID` / `Secret access key`
- 需要 `Hosted Zone ID` 与 `record_name`
- 建议权限包含：
  - `route53:ListHostedZones`
  - `route53:ListResourceRecordSets`
  - `route53:ChangeResourceRecordSets`

### 5. 华为云 DNS

- 当前程序使用 `X-Auth-Token`
- 可通过华为云 IAM 鉴权接口获取临时 Token
- 需要 `zone_id` 与 `record_name`

### 6. Google Cloud DNS

- 当前程序使用 `Access Token`
- 需具备 Cloud DNS 管理权限
- 需要 `project_id`、`managed_zone`、`record_name`

### 7. Azure DNS

- 当前程序使用 Azure 管理 API `Access Token`
- Token 资源为：`https://management.azure.com/`
- 需要 `subscription_id`、`resource_group`、`zone_name`、`record_name`

## ☁️ Worker 部署（仅 cfworker.js）

部署说明见：

- [docs/WORKER_DEPLOY.md](docs/WORKER_DEPLOY.md)

## ⚙️ 配置说明（核心字段）

- `settings.ip_api_url`：官方源地址
- `settings.custom_ip_api_url`：自定义源地址
- `settings.max_ips`：延迟测速并发（`cfst -n`）
- `settings.top_n`：下载测速候选（`cfst -dn`）
- `settings.timeout`：请求超时
- `settings.max_retries`：单轮失败重试次数
- `telegram.bot_token` / `telegram.chat_id`
- `dns_profiles`：多域名配置

## 🔐 安全建议

- 建议使用最小权限 API Token
- 测速前关闭代理/VPN，避免结果失真

## 🙏 致谢

- 本项目：<https://github.com/wzlinbin/CloudFlareIP-RenewDNS>
- 测速能力来源：<https://github.com/XIU2/CloudflareSpeedTest>
- 讨论 TG：<https://t.me/iprenewdns>
