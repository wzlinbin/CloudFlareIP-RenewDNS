---

# 🚀 CloudFlareIP-RenewDNS

一个基于 Cloudflare Workers 的优选 IP 聚合、清洗与运营商自动分类工具。

## ✨ 特性

* **多源聚合**：自动从 7+ 个优选 IP 接口抓取数据。
* **智能清洗**：自动剔除无效 IP，支持按 **电信、联通、移动** 自动分类展示。
* **美观 UI**：内置现代化深色模式仪表盘，支持一键复制去重列表。
* **专项代理**：内置 Telegram (`/tg`) 和 Cloudflare (`/cf`) API 代理功能。
* **自动联动**：修改配置即可自动更新 UI。

---

## 🛠️ 如何部署到你自己的 Cloudflare

### 方法一：手动部署 (最快)

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com/)。
2. 进入 **Workers & Pages** -> **Create application** -> **Create Worker**。
3. 复制本仓库中 `worker.js` 的完整代码。
4. 在 Worker 编辑器中粘贴代码并点击 **Save and deploy**。

### 方法二：通过 GitHub Actions 自动部署 (推荐)

[![Deploy to Cloudflare Workers](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/wzlinbin/CloudFlareIP-RenewDNS/new/main?filename=README.md)


---

## 📖 使用指南

* **根路径 (`/`)**：访问美观的聚合仪表盘（浏览器访问）或获取 JSON 数据（API 访问）。
* **TG 代理**：访问 `你的域名/tg/bot<token>/sendMessage`。
* **CF 代理**：访问 `你的域名/cf/client/v4/zones`。

---

## 📝 贡献与反馈

如果你有任何建议或发现了 Bug，欢迎提交 [Issues]。

---
