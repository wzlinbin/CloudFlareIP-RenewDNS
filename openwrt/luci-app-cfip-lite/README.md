# luci-app-cfip-lite

独立 OpenWrt LuCI 应用，不依赖现有项目的 `main.py`。

## 功能

- 中文 LuCI 页面配置
- 官方源/自定义源测速
- 可选 Cloudflare DNS 自动更新
- Telegram 消息推送（支持多个 Chat ID）
- 运行前自动停用代理并在结束后恢复（可配置服务列表）
- 最近日志展示：`/tmp/cfip-lite.log`

## 组成

- `root/etc/config/cfip`：UCI 默认配置
- `root/usr/lib/lua/luci/controller/cfip.lua`：LuCI 菜单入口
- `root/usr/lib/lua/luci/model/cbi/cfip.lua`：LuCI 中文配置页
- `root/usr/libexec/cfip/run.sh`：读取 UCI 并启动执行器
- `root/usr/libexec/cfip/cfip_lite.py`：独立执行逻辑

## 官方源鉴权链路

`Client ID/Secret 签名` -> `一次性注册凭据` -> `x-auth-key 回退`

## 依赖

- `python3`
- `python3-requests`
- CloudflareST 二进制（默认路径：`/usr/bin/CloudflareST`）
