# ☁️ Cloudflare Worker 部署指引（仅 cfworker.js）

本文档仅说明如何部署 `cfworker.js`。

## 1. 📌 功能说明

`cfworker.js` 提供以下能力：

- `GET /`：聚合多个来源的 Cloudflare IPv4（JSON/HTML）
- `/tg/*`：转发 Telegram Bot API
- `/cf/*`：转发 Cloudflare API

说明：

- 该脚本不依赖 KV，不需要绑定 KV Namespace。
- 该脚本不包含签名鉴权逻辑，部署步骤更简单。

## 2. 🧰 前置条件

- Cloudflare 账号
- Node.js（建议 LTS）
- Wrangler CLI

```bash
npm i -g wrangler
wrangler login
```

## 3. 📝 配置 wrangler.toml

确保 `main` 指向 `cfworker.js`：

```toml
name = "cloudflareip-renewdns"
main = "cfworker.js"
compatibility_date = "2026-03-01"
```

## 4. ✅ 本地检查

```bash
node --check cfworker.js
```

## 5. 🚀 部署

```bash
wrangler deploy
```

部署成功后会得到类似地址：

- `https://<worker-name>.<subdomain>.workers.dev/`
- `https://<worker-name>.<subdomain>.workers.dev/tg/...`
- `https://<worker-name>.<subdomain>.workers.dev/cf/...`

## 6. 🌐 自定义域名（可选）

在 Cloudflare Dashboard 的 Worker 路由中绑定域名，例如：

- `https://your-domain.example.com/*`

## 7. 🧪 接口验证

### 7.1 📊 聚合接口

```bash
curl -i https://<worker-domain>/
```

返回 JSON（默认）或 HTML（请求头 `Accept: text/html`）。

### 7.2 📨 TG 代理

```bash
curl -i "https://<worker-domain>/tg/bot<token>/getMe"
```

### 7.3 🛡️ Cloudflare 代理

```bash
curl -i "https://<worker-domain>/cf/client/v4/user/tokens/verify"
```

## 8. 🔗 与 main.py 对接

你的主程序默认官方源是：

- `https://cloudflareip.ocisg.xyz/api/data`

如果改用你自己部署的 `cfworker.js`，请在程序中设置“自定义优选IP源地址”为：

- `https://<worker-domain>/`

原因：

- `cfworker.js` 的聚合数据接口在根路径 `/`，不是 `/api/data`。

## 9. 🤖 GitHub Actions 自动部署（可选）

仓库已有 `.github/workflows/deploy.yml`。  
需要在 GitHub Secrets 配置：

- `CLOUDFLARE_API_TOKEN`

推送到 `main` 分支后会自动执行 `wrangler deploy`。

## 10. ❓ 常见问题

- `main` 配置错了：请确认 `wrangler.toml` 使用 `main = "cfworker.js"`。
- 访问 `/` 失败：检查 Worker 是否部署成功、域名路由是否正确。
- `tg/cf` 转发失败：检查上游 API 状态、Token 权限和网络连通性。
