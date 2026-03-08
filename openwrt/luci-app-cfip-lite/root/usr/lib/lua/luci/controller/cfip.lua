module("luci.controller.cfip", package.seeall)
local fs = require "nixio.fs"

function index()
	if not fs.access("/etc/config/cfip") then
		return
	end

	entry({"admin", "services", "cfip"}, cbi("cfip"), _("CFIP Lite"), 80).dependent = true
end
