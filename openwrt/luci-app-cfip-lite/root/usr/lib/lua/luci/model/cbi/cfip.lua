local sys = require "luci.sys"
local util = require "luci.util"

local m = Map("cfip", translate("CFIP 优选"), translate("保存并应用后会自动更新定时任务，按计划执行。"))
local s = m:section(TypedSection, "cfip", translate("基础设置"))
s.anonymous = true
s.addremove = false

local enabled = s:option(Flag, "enabled", translate("启用"))
enabled.default = "0"
enabled.rmempty = false

local schedule_mode = s:option(ListValue, "schedule_mode", translate("运行频率"))
schedule_mode:value("daily", translate("每天"))
schedule_mode:value("weekly", translate("每周"))
schedule_mode:value("monthly", translate("每月"))
schedule_mode.default = "daily"
schedule_mode.rmempty = false

local schedule_hour = s:option(Value, "schedule_hour", translate("运行小时（0-23）"))
schedule_hour.default = "3"
schedule_hour.rmempty = false
function schedule_hour.validate(self, value, section)
	local n = tonumber(value)
	if not n or n < 0 or n > 23 then
		return nil, translate("请输入 0 到 23 的整数。")
	end
	return tostring(math.floor(n))
end

local schedule_weekday = s:option(ListValue, "schedule_weekday", translate("每周几运行"))
schedule_weekday:value("0", translate("周日"))
schedule_weekday:value("1", translate("周一"))
schedule_weekday:value("2", translate("周二"))
schedule_weekday:value("3", translate("周三"))
schedule_weekday:value("4", translate("周四"))
schedule_weekday:value("5", translate("周五"))
schedule_weekday:value("6", translate("周六"))
schedule_weekday.default = "1"
schedule_weekday:depends("schedule_mode", "weekly")
schedule_weekday.rmempty = true

local schedule_monthday = s:option(Value, "schedule_monthday", translate("每月几号运行（1-31）"))
schedule_monthday.default = "1"
schedule_monthday:depends("schedule_mode", "monthly")
schedule_monthday.rmempty = true
function schedule_monthday.validate(self, value, section)
	local n = tonumber(value)
	if not n or n < 1 or n > 31 then
		return nil, translate("请输入 1 到 31 的整数。")
	end
	return tostring(math.floor(n))
end

local run_mode = s:option(ListValue, "run_mode", translate("运行模式"))
run_mode:value("dns_update", translate("测速并更新 DNS"))
run_mode:value("speed_only", translate("仅测速，不更新 DNS"))
run_mode.default = "dns_update"
run_mode.rmempty = false

local source_mode = s:option(ListValue, "source_mode", translate("IP 源类型"))
source_mode:value("official", translate("官方源（系统预设）"))
source_mode:value("custom", translate("自定义源"))
source_mode.default = "official"
source_mode.rmempty = false

local custom_ip_api_url = s:option(Value, "custom_ip_api_url", translate("自定义源地址"))
custom_ip_api_url:depends("source_mode", "custom")
custom_ip_api_url.rmempty = true
custom_ip_api_url.description =
	"<a href=\"https://github.com/wzlinbin/CloudFlareIP-RenewDNS/blob/main/docs/WORKER_DEPLOY.md\" target=\"_blank\" rel=\"noopener noreferrer\">私有化部署优选IP聚合源</a>"

local auto_register_once = s:option(Flag, "auto_register_once", translate("自动注册一次性凭据"))
auto_register_once.default = "1"
auto_register_once:depends("source_mode", "official")
auto_register_once.rmempty = true

local invite_code = s:option(Value, "invite_code", translate("邀请码（可选）"))
invite_code:depends("source_mode", "official")
invite_code.rmempty = true

local auth_ephemeral_ttl_sec = s:option(Value, "auth_ephemeral_ttl_sec", translate("一次性凭据有效期（秒）"))
auth_ephemeral_ttl_sec.default = "180"
auth_ephemeral_ttl_sec:depends("source_mode", "official")
auth_ephemeral_ttl_sec.rmempty = true
function auth_ephemeral_ttl_sec.validate(self, value, section)
	if value == nil or value == "" then
		return "180"
	end
	local n = tonumber(value)
	if not n or n < 30 or n > 1800 then
		return nil, translate("请输入 30 到 1800 的整数。")
	end
	return tostring(math.floor(n))
end

local cf_api_token = s:option(Value, "cf_api_token", translate("Cloudflare API Token"))
cf_api_token.password = true
cf_api_token.rmempty = true
cf_api_token:depends("run_mode", "dns_update")

local cf_zone_id = s:option(Value, "cf_zone_id", translate("Cloudflare Zone ID"))
cf_zone_id.rmempty = true
cf_zone_id:depends("run_mode", "dns_update")

local cf_dns_name = s:option(Value, "cf_dns_name", translate("DNS 记录名"))
cf_dns_name.placeholder = "www.example.com"
cf_dns_name.rmempty = true
cf_dns_name:depends("run_mode", "dns_update")

local tg_enabled = s:option(Flag, "tg_enabled", translate("启用 Telegram 推送"))
tg_enabled.default = "0"
tg_enabled.rmempty = false

local tg_bot_token = s:option(Value, "tg_bot_token", translate("Telegram Bot Token"))
tg_bot_token.password = true
tg_bot_token:depends("tg_enabled", "1")
tg_bot_token.rmempty = true

local tg_chat_id = s:option(Value, "tg_chat_id", translate("Telegram Chat ID"))
tg_chat_id:depends("tg_enabled", "1")
tg_chat_id.placeholder = "123456789,987654321"
tg_chat_id.description = translate("支持多个 Chat ID，使用英文逗号分隔。")
tg_chat_id.rmempty = true

local tg_disable_preview = s:option(Flag, "tg_disable_preview", translate("禁用链接预览"))
tg_disable_preview.default = "1"
tg_disable_preview:depends("tg_enabled", "1")
tg_disable_preview.rmempty = false

local tg_timeout = s:option(Value, "tg_timeout", translate("Telegram 请求超时（秒）"))
tg_timeout.default = "10"
tg_timeout:depends("tg_enabled", "1")
tg_timeout.rmempty = true
function tg_timeout.validate(self, value, section)
	if value == nil or value == "" then
		return "10"
	end
	local n = tonumber(value)
	if not n or n < 1 or n > 120 then
		return nil, translate("请输入 1 到 120 的整数。")
	end
	return tostring(math.floor(n))
end

local proxy_guard = s:option(Flag, "proxy_guard", translate("测速前自动停用代理并在结束后恢复"))
proxy_guard.default = "1"
proxy_guard.rmempty = false

local proxy_services = s:option(Value, "proxy_services", translate("代理服务列表"))
proxy_services.placeholder = "passwall passwall2 shadowsocksr ssr-plus"
proxy_services.description = translate("支持空格或英文逗号分隔。仅恢复原本运行中的服务。")
proxy_services:depends("proxy_guard", "1")
proxy_services.rmempty = true

local max_ips = s:option(Value, "max_ips", translate("测速并发数（cfst -n）"))
max_ips.default = "200"
max_ips.rmempty = true
function max_ips.validate(self, value, section)
	if value == nil or value == "" then
		return "200"
	end
	local n = tonumber(value)
	if not n or n < 1 or n > 5000 then
		return nil, translate("请输入 1 到 5000 的整数。")
	end
	return tostring(math.floor(n))
end

local top_n = s:option(Value, "top_n", translate("下载测速数量（cfst -dn）"))
top_n.default = "10"
top_n.rmempty = true
function top_n.validate(self, value, section)
	if value == nil or value == "" then
		return "10"
	end
	local n = tonumber(value)
	if not n or n < 1 or n > 200 then
		return nil, translate("请输入 1 到 200 的整数。")
	end
	return tostring(math.floor(n))
end

local timeout = s:option(Value, "timeout", translate("HTTP 超时（秒）"))
timeout.default = "15"
timeout.rmempty = true
function timeout.validate(self, value, section)
	if value == nil or value == "" then
		return "15"
	end
	local n = tonumber(value)
	if not n or n < 1 or n > 120 then
		return nil, translate("请输入 1 到 120 的整数。")
	end
	return tostring(math.floor(n))
end

local max_retries = s:option(Value, "max_retries", translate("测速重试次数"))
max_retries.default = "3"
max_retries.rmempty = true
function max_retries.validate(self, value, section)
	if value == nil or value == "" then
		return "3"
	end
	local n = tonumber(value)
	if not n or n < 1 or n > 10 then
		return nil, translate("请输入 1 到 10 的整数。")
	end
	return tostring(math.floor(n))
end

local python_bin = s:option(Value, "python_bin", translate("Python 路径"))
python_bin.default = "/usr/bin/python3"
python_bin.rmempty = true

local cfst_path = s:option(Value, "cfst_path", translate("CloudflareST 路径"))
cfst_path.default = "/usr/bin/CloudflareST"
cfst_path.rmempty = true

local script_path = s:option(Value, "script_path", translate("独立运行脚本路径"))
script_path.default = "/usr/libexec/cfip/cfip_lite.py"
script_path.rmempty = true

local work_dir = s:option(Value, "work_dir", translate("工作目录"))
work_dir.default = "/tmp/cfip-lite"
work_dir.rmempty = true

local cron_preview = s:option(DummyValue, "_cron_preview", translate("当前计划任务"))
cron_preview.rawhtml = true
function cron_preview.cfgvalue(self, section)
	local line = sys.exec("grep 'cfip-lite-schedule' /etc/crontabs/root 2>/dev/null | tail -n 1")
	if not line or #line == 0 then
		line = "未安装定时任务（保存并应用后自动生成）"
	end
	return "<pre style='white-space:pre-wrap;max-height:120px;overflow:auto'>" .. util.pcdata(line) .. "</pre>"
end

local logv = s:option(DummyValue, "_last_log", translate("最近日志"))
logv.rawhtml = true
function logv.cfgvalue(self, section)
	local text = sys.exec("tail -n 120 /tmp/cfip-lite.log 2>/dev/null")
	if not text or #text == 0 then
		text = "暂无日志，等待定时任务触发后刷新本页查看。"
	end
	return "<pre style='white-space:pre-wrap;max-height:360px;overflow:auto'>" .. util.pcdata(text) .. "</pre>"
end

function m.on_after_commit(self)
	sys.call("sh /usr/libexec/cfip/schedule_apply.sh >/tmp/cfip-schedule.log 2>&1")
end

return m
