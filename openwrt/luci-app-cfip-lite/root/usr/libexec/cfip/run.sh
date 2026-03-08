#!/bin/sh
set -eu

uci_get() {
	uci -q get "cfip.main.$1" 2>/dev/null || true
}

log() {
	printf '%s\n' "$*"
}

RESTORE_SERVICES=""
RESTORE_DONE=0
LOCK_DIR=""
LOCK_RELEASED=0
SERVICE_OP_TIMEOUT=20

service_process_patterns() {
	svc="$1"
	case "$svc" in
		passwall)
			echo "xray sing-box chinadns-ng dns2socks brook hysteria2 tuic-client passwall"
			;;
		passwall2)
			echo "xray sing-box chinadns-ng dns2socks brook hysteria2 tuic-client passwall2"
			;;
		shadowsocksr|ssr-plus)
			echo "ss-redir ss-local ssr-redir ssr-local ssr-server v2ray-plugin xray sing-box shadowsocksr"
			;;
		*)
			echo "$svc"
			;;
	esac
}

has_service_process() {
	svc="$1"
	patterns="$(service_process_patterns "${svc}")"
	for p in ${patterns}; do
		if pidof "${p}" >/dev/null 2>&1; then
			return 0
		fi
	done
	return 1
}

is_service_running() {
	svc="$1"
	[ -x "/etc/init.d/${svc}" ] || return 1

	if "/etc/init.d/${svc}" running >/dev/null 2>&1; then
		has_service_process "${svc}" && return 0
	fi

	if "/etc/init.d/${svc}" status >/dev/null 2>&1; then
		has_service_process "${svc}" && return 0
	fi

	return 1
}

run_service_action_with_timeout() {
	svc="$1"
	action="$2"
	timeout_sec="$3"

	"/etc/init.d/${svc}" "${action}" >/dev/null 2>&1 &
	cmd_pid="$!"
	sec=0
	while kill -0 "${cmd_pid}" >/dev/null 2>&1; do
		if [ "${sec}" -ge "${timeout_sec}" ]; then
			kill "${cmd_pid}" >/dev/null 2>&1 || true
			sleep 1
			kill -9 "${cmd_pid}" >/dev/null 2>&1 || true
			return 124
		fi
		sec=$((sec + 1))
		sleep 1
	done

	wait "${cmd_pid}" >/dev/null 2>&1
}

stop_proxy_services() {
	[ "${PROXY_GUARD}" = "1" ] || return 0

	RESTORE_SERVICES=""
	for svc in ${PROXY_SERVICES}; do
		[ -x "/etc/init.d/${svc}" ] || continue
		if is_service_running "${svc}"; then
			log "proxy guard: stopping ${svc}"
			if run_service_action_with_timeout "${svc}" stop "${SERVICE_OP_TIMEOUT}"; then
				RESTORE_SERVICES="${RESTORE_SERVICES} ${svc}"
			else
				log "proxy guard: failed to stop ${svc}"
			fi
		else
			log "proxy guard: skip ${svc} (not running or no process)"
		fi
	done
}

restore_proxy_services() {
	[ "${RESTORE_DONE}" = "0" ] || return 0
	RESTORE_DONE=1
	[ "${PROXY_GUARD}" = "1" ] || return 0
	[ -n "${RESTORE_SERVICES}" ] || return 0

	for svc in ${RESTORE_SERVICES}; do
		[ -x "/etc/init.d/${svc}" ] || continue
		log "proxy guard: restoring ${svc}"
		if run_service_action_with_timeout "${svc}" start "${SERVICE_OP_TIMEOUT}"; then
			if has_service_process "${svc}"; then
				log "proxy guard: restored ${svc}"
			else
				log "proxy guard: ${svc} started but process not detected"
			fi
		else
			log "proxy guard: failed to start ${svc}"
		fi
	done
}

acquire_lock() {
	LOCK_DIR="${WORK_DIR%/}/.cfip-run.lock"
	if mkdir "${LOCK_DIR}" >/dev/null 2>&1; then
		return 0
	fi
	log "another cfip task is already running, skip this run."
	return 1
}

release_lock() {
	[ "${LOCK_RELEASED}" = "0" ] || return 0
	LOCK_RELEASED=1
	[ -n "${LOCK_DIR}" ] || return 0
	rmdir "${LOCK_DIR}" >/dev/null 2>&1 || true
}

to_int() {
	v="$1"
	d="$2"
	case "$v" in
		''|*[!0-9]*) echo "$d" ;;
		*) echo "$v" ;;
	esac
}

url_origin() {
	u="$1"
	echo "${u}" | sed -n 's#^\(https\?://[^/]*\).*#\1#p'
}

ENABLED="$(uci_get enabled)"
if [ "${ENABLED:-0}" != "1" ]; then
	log "cfip is disabled, skip run."
	exit 0
fi

RUN_MODE="$(uci_get run_mode)"
SOURCE_MODE="$(uci_get source_mode)"
IP_API_URL="$(uci_get ip_api_url)"
CUSTOM_IP_API_URL="$(uci_get custom_ip_api_url)"
AUTH_KEY="$(uci_get auth_key)"
AUTH_CLIENT_ID="$(uci_get auth_client_id)"
AUTH_CLIENT_SECRET="$(uci_get auth_client_secret)"
AUTH_HWID="$(uci_get auth_hwid)"
AUTO_REGISTER_ONCE="$(uci_get auto_register_once)"
INVITE_CODE="$(uci_get invite_code)"
AUTH_EPHEMERAL_TTL_SEC="$(to_int "$(uci_get auth_ephemeral_ttl_sec)" 180)"
CF_API_TOKEN="$(uci_get cf_api_token)"
CF_ZONE_ID="$(uci_get cf_zone_id)"
CF_DNS_NAME="$(uci_get cf_dns_name)"
TG_ENABLED="$(uci_get tg_enabled)"
TG_BOT_TOKEN="$(uci_get tg_bot_token)"
TG_CHAT_ID="$(uci_get tg_chat_id)"
TG_PROXY_BASE_URL="$(uci_get tg_proxy_base_url)"
TG_AUTH_KEY="$(uci_get tg_auth_key)"
TG_DISABLE_PREVIEW="$(uci_get tg_disable_preview)"
TG_TIMEOUT="$(to_int "$(uci_get tg_timeout)" 10)"
PROXY_GUARD="$(uci_get proxy_guard)"
PROXY_SERVICES="$(uci_get proxy_services)"
MAX_IPS="$(to_int "$(uci_get max_ips)" 200)"
TOP_N="$(to_int "$(uci_get top_n)" 10)"
TIMEOUT="$(to_int "$(uci_get timeout)" 15)"
MAX_RETRIES="$(to_int "$(uci_get max_retries)" 3)"
PYTHON_BIN="$(uci_get python_bin)"
CFST_PATH="$(uci_get cfst_path)"
SCRIPT_PATH="$(uci_get script_path)"
WORK_DIR="$(uci_get work_dir)"

[ -n "${RUN_MODE}" ] || RUN_MODE="dns_update"
[ -n "${SOURCE_MODE}" ] || SOURCE_MODE="official"
[ -n "${IP_API_URL}" ] || IP_API_URL="https://cloudflareip.ocisg.xyz/api/data"
[ -n "${AUTO_REGISTER_ONCE}" ] || AUTO_REGISTER_ONCE="1"
[ -n "${TG_ENABLED}" ] || TG_ENABLED="0"
[ -n "${TG_PROXY_BASE_URL}" ] || TG_PROXY_BASE_URL="https://cloudflareip.ocisg.xyz"
[ -n "${TG_DISABLE_PREVIEW}" ] || TG_DISABLE_PREVIEW="1"
[ -n "${PROXY_GUARD}" ] || PROXY_GUARD="1"
[ -n "${PROXY_SERVICES}" ] || PROXY_SERVICES="passwall passwall2 shadowsocksr ssr-plus"
PROXY_SERVICES="$(echo "${PROXY_SERVICES}" | tr ',' ' ')"
[ -n "${PYTHON_BIN}" ] || PYTHON_BIN="/usr/bin/python3"
[ -n "${CFST_PATH}" ] || CFST_PATH="/usr/bin/CloudflareST"
[ -n "${SCRIPT_PATH}" ] || SCRIPT_PATH="/usr/libexec/cfip/cfip_lite.py"
[ -n "${WORK_DIR}" ] || WORK_DIR="/tmp/cfip-lite"

if [ "${SOURCE_MODE}" = "custom" ] && [ -n "${CUSTOM_IP_API_URL}" ]; then
	CUSTOM_ORIGIN="$(url_origin "${CUSTOM_IP_API_URL}")"
	if [ -n "${CUSTOM_ORIGIN}" ]; then
		TG_PROXY_BASE_URL="${CUSTOM_ORIGIN}"
	else
		TG_PROXY_BASE_URL="${CUSTOM_IP_API_URL}"
	fi
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
	log "error: python not found: ${PYTHON_BIN}"
	exit 2
fi

if [ ! -f "${SCRIPT_PATH}" ]; then
	log "error: runner script not found: ${SCRIPT_PATH}"
	exit 2
fi

if [ "${RUN_MODE}" = "dns_update" ]; then
	if [ -z "${CF_API_TOKEN}" ] || [ -z "${CF_ZONE_ID}" ] || [ -z "${CF_DNS_NAME}" ]; then
		log "error: dns_update mode requires cf_api_token / cf_zone_id / cf_dns_name"
		exit 2
	fi
fi

if [ "${SOURCE_MODE}" = "custom" ] && [ -z "${CUSTOM_IP_API_URL}" ]; then
	log "error: custom source mode requires custom_ip_api_url"
	exit 2
fi

mkdir -p "${WORK_DIR}"

if ! acquire_lock; then
	exit 11
fi

trap 'restore_proxy_services; release_lock' EXIT INT TERM
stop_proxy_services

log "start: ${PYTHON_BIN} ${SCRIPT_PATH}"
set +e
if [ "${SOURCE_MODE}" = "custom" ]; then
	"${PYTHON_BIN}" "${SCRIPT_PATH}" \
		--run-mode "${RUN_MODE}" \
		--source-mode "${SOURCE_MODE}" \
		--ip-api-url "${IP_API_URL}" \
		--custom-ip-api-url "${CUSTOM_IP_API_URL}" \
		--auth-key "${AUTH_KEY}" \
		--auth-client-id "${AUTH_CLIENT_ID}" \
		--auth-client-secret "${AUTH_CLIENT_SECRET}" \
		--auth-hwid "${AUTH_HWID}" \
		--auto-register-once "${AUTO_REGISTER_ONCE}" \
		--invite-code "${INVITE_CODE}" \
		--auth-ephemeral-ttl-sec "${AUTH_EPHEMERAL_TTL_SEC}" \
		--cf-api-token "${CF_API_TOKEN}" \
		--cf-zone-id "${CF_ZONE_ID}" \
		--cf-dns-name "${CF_DNS_NAME}" \
		--tg-enabled "${TG_ENABLED}" \
		--tg-bot-token "${TG_BOT_TOKEN}" \
		--tg-chat-id "${TG_CHAT_ID}" \
		--tg-proxy-base-url "${TG_PROXY_BASE_URL}" \
		--tg-auth-key "${TG_AUTH_KEY}" \
		--tg-disable-preview "${TG_DISABLE_PREVIEW}" \
		--tg-timeout "${TG_TIMEOUT}" \
		--max-ips "${MAX_IPS}" \
		--top-n "${TOP_N}" \
		--timeout "${TIMEOUT}" \
		--max-retries "${MAX_RETRIES}" \
		--cfst-path "${CFST_PATH}" \
		--work-dir "${WORK_DIR}"
else
	"${PYTHON_BIN}" "${SCRIPT_PATH}" \
		--run-mode "${RUN_MODE}" \
		--source-mode "${SOURCE_MODE}" \
		--ip-api-url "${IP_API_URL}" \
		--auth-key "${AUTH_KEY}" \
		--auth-client-id "${AUTH_CLIENT_ID}" \
		--auth-client-secret "${AUTH_CLIENT_SECRET}" \
		--auth-hwid "${AUTH_HWID}" \
		--auto-register-once "${AUTO_REGISTER_ONCE}" \
		--invite-code "${INVITE_CODE}" \
		--auth-ephemeral-ttl-sec "${AUTH_EPHEMERAL_TTL_SEC}" \
		--cf-api-token "${CF_API_TOKEN}" \
		--cf-zone-id "${CF_ZONE_ID}" \
		--cf-dns-name "${CF_DNS_NAME}" \
		--tg-enabled "${TG_ENABLED}" \
		--tg-bot-token "${TG_BOT_TOKEN}" \
		--tg-chat-id "${TG_CHAT_ID}" \
		--tg-proxy-base-url "${TG_PROXY_BASE_URL}" \
		--tg-auth-key "${TG_AUTH_KEY}" \
		--tg-disable-preview "${TG_DISABLE_PREVIEW}" \
		--tg-timeout "${TG_TIMEOUT}" \
		--max-ips "${MAX_IPS}" \
		--top-n "${TOP_N}" \
		--timeout "${TIMEOUT}" \
		--max-retries "${MAX_RETRIES}" \
		--cfst-path "${CFST_PATH}" \
		--work-dir "${WORK_DIR}"
fi
RET="$?"
set -e

log "done, exit code: ${RET}"
exit "${RET}"
