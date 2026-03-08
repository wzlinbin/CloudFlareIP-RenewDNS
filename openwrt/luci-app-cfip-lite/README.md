# luci-app-cfip-lite

Standalone LuCI app for OpenWrt.

This app is independent from the existing project scripts and does not call `main.py`.

## Features

- LuCI form to input Cloudflare and speed-test settings
- `Run Once` button to run a standalone runner
- Last-run log at `/tmp/cfip-lite.log`

## Components

- `root/etc/config/cfip`  
  UCI defaults
- `root/usr/lib/lua/luci/controller/cfip.lua`  
  LuCI menu entry
- `root/usr/lib/lua/luci/model/cbi/cfip.lua`  
  LuCI form page
- `root/usr/libexec/cfip/run.sh`  
  UCI reader + launcher
- `root/usr/libexec/cfip/cfip_lite.py`  
  Standalone workflow:
  - fetch IPs from API
  - run CloudflareST
  - parse best IP
  - optional Cloudflare DNS update

## Requirements

- `python3`
- `python3-requests`
- CloudflareST binary (default `/usr/bin/CloudflareST`)

## Quick use

1. Deploy `root/` files to matching paths on OpenWrt.
2. Ensure execute permission:  
   `chmod +x /usr/libexec/cfip/run.sh`
3. Restart web UI:  
   `/etc/init.d/uhttpd restart`
4. Open `Services -> CFIP Lite`, fill values, click `Run Once`.

