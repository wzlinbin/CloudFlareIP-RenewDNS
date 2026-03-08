# ☁️ Cloudflare Worker 部署指引（仅 cfworker.js）

本指引仅说明 `cfworker.js`，并使用 Cloudflare 官方一键部署按钮，不使用 Wrangler 命令行。

## 🚀 一键部署

[![Deploy to Cloudflare Workers](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/deploy/?url=https://github.com/wzlinbin/CloudFlareIP-RenewDNS/tree/main)

## 📋 部署前准备

- 你需要有 Cloudflare 账号并已登录
- 建议先 Fork 本项目到你的 GitHub（便于后续自行维护）

## 🧭 部署步骤

1. 点击上方 `Deploy to Cloudflare Workers` 按钮
2. 在 Cloudflare 页面授权并确认部署仓库
3. 按向导完成 Worker 创建
4. 部署成功后获得 `workers.dev` 地址

## ✅ 部署后验证

部署成功后可访问：

- `https://<你的worker域名>/`（IP 聚合接口，返回 JSON/HTML）
- `https://<你的worker域名>/tg/...`（Telegram API 代理）
- `https://<你的worker域名>/cf/...`（Cloudflare API 代理）

示例验证：

```text
https://<你的worker域名>/
https://<你的worker域名>/tg/bot<token>/getMe
https://<你的worker域名>/cf/client/v4/user/tokens/verify
```

## 🔗 与主程序 main.py 对接

`cfworker.js` 的聚合接口在根路径 `/`，不是 `/api/data`。

在程序中配置“自定义优选IP源地址”时请填写：

```text
https://<你的worker域名>/
```

## 🌐 自定义域名（可选）

如需绑定自己的域名，可在 Cloudflare Dashboard 的 Worker 路由中配置：

- `https://your-domain.example.com/*`

## ❓ 常见问题

- 打开 `/` 报错：检查 Worker 是否部署成功、域名是否生效
- `/tg` 或 `/cf` 请求失败：检查上游 API Token/权限、目标接口是否可用
- 主程序读不到数据：确认你填的是根路径 `/`，并非 `/api/data`
