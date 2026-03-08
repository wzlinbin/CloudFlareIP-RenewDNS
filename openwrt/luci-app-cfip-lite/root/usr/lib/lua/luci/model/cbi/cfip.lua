local sys = require "luci.sys"
local util = require "luci.util"

local m = Map("cfip", translate("CFIP Lite"), translate("Configure and run CFIP in a minimal OpenWrt flow."))
local s = m:section(TypedSection, "cfip", translate("Basic Settings"))
s.anonymous = true
s.addremove = false

local enabled = s:option(Flag, "enabled", translate("Enable"))
enabled.default = "0"
enabled.rmempty = false

local run_mode = s:option(ListValue, "run_mode", translate("Run Mode"))
run_mode:value("dns_update", translate("Speed test + DNS update"))
run_mode:value("speed_only", translate("Speed test only"))
run_mode.default = "dns_update"
run_mode.rmempty = false

local source_mode = s:option(ListValue, "source_mode", translate("IP Source"))
source_mode:value("official", translate("Official"))
source_mode:value("custom", translate("Custom"))
source_mode.default = "official"
source_mode.rmempty = false

local ip_api_url = s:option(Value, "ip_api_url", translate("Official API URL"))
ip_api_url.default = "https://cloudflareip.ocisg.xyz/api/data"
ip_api_url.rmempty = false

local custom_ip_api_url = s:option(Value, "custom_ip_api_url", translate("Custom API URL"))
custom_ip_api_url:depends("source_mode", "custom")
custom_ip_api_url.rmempty = true

local cf_api_token = s:option(Value, "cf_api_token", translate("Cloudflare API Token"))
cf_api_token.password = true
cf_api_token.rmempty = false
cf_api_token:depends("run_mode", "dns_update")

local cf_zone_id = s:option(Value, "cf_zone_id", translate("Cloudflare Zone ID"))
cf_zone_id.rmempty = false
cf_zone_id:depends("run_mode", "dns_update")

local cf_dns_name = s:option(Value, "cf_dns_name", translate("DNS Record Name"))
cf_dns_name.placeholder = "www.example.com"
cf_dns_name.rmempty = false
cf_dns_name:depends("run_mode", "dns_update")

local max_ips = s:option(Value, "max_ips", translate("Max test IPs (cfst -n)"))
max_ips.datatype = "uinteger"
max_ips.default = "200"
max_ips.rmempty = false

local top_n = s:option(Value, "top_n", translate("Download test count (cfst -dn)"))
top_n.datatype = "uinteger"
top_n.default = "10"
top_n.rmempty = false

local timeout = s:option(Value, "timeout", translate("Request timeout (s)"))
timeout.datatype = "uinteger"
timeout.default = "15"
timeout.rmempty = false

local max_retries = s:option(Value, "max_retries", translate("Retry count"))
max_retries.datatype = "uinteger"
max_retries.default = "3"
max_retries.rmempty = false

local python_bin = s:option(Value, "python_bin", translate("Python path"))
python_bin.default = "/usr/bin/python3"
python_bin.rmempty = false

local cfst_path = s:option(Value, "cfst_path", translate("CloudflareST path"))
cfst_path.default = "/usr/bin/CloudflareST"
cfst_path.rmempty = false

local script_path = s:option(Value, "script_path", translate("Runner script path"))
script_path.default = "/usr/libexec/cfip/cfip_lite.py"
script_path.rmempty = false

local work_dir = s:option(Value, "work_dir", translate("Work dir"))
work_dir.default = "/tmp/cfip-lite"
work_dir.rmempty = false

local run_btn = s:option(Button, "_run_now", translate("Run Now"))
run_btn.inputtitle = translate("Run Once")
run_btn.inputstyle = "apply"
function run_btn.write(self, section)
	sys.call("sh /usr/libexec/cfip/run.sh >/tmp/cfip-lite.log 2>&1 &")
end

local logv = s:option(DummyValue, "_last_log", translate("Last Log"))
logv.rawhtml = true
function logv.cfgvalue(self, section)
	local text = sys.exec("tail -n 120 /tmp/cfip-lite.log 2>/dev/null")
	if not text or #text == 0 then
		text = "No log yet. Click Run Once, then refresh this page."
	end
	return "<pre style='white-space:pre-wrap;max-height:360px;overflow:auto'>" .. util.pcdata(text) .. "</pre>"
end

return m
