#!/bin/sh
set -eu

uci_get() {
	uci -q get "cfip.main.$1" 2>/dev/null || true
}

log() {
	printf '%s\n' "$*"
}

to_int() {
	v="$1"
	d="$2"
	case "$v" in
		''|*[!0-9]*) echo "$d" ;;
		*) echo "$v" ;;
	esac
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
CF_API_TOKEN="$(uci_get cf_api_token)"
CF_ZONE_ID="$(uci_get cf_zone_id)"
CF_DNS_NAME="$(uci_get cf_dns_name)"
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
[ -n "${PYTHON_BIN}" ] || PYTHON_BIN="/usr/bin/python3"
[ -n "${CFST_PATH}" ] || CFST_PATH="/usr/bin/CloudflareST"
[ -n "${SCRIPT_PATH}" ] || SCRIPT_PATH="/usr/libexec/cfip/cfip_lite.py"
[ -n "${WORK_DIR}" ] || WORK_DIR="/tmp/cfip-lite"

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

log "start: ${PYTHON_BIN} ${SCRIPT_PATH}"
set +e
if [ "${SOURCE_MODE}" = "custom" ]; then
	"${PYTHON_BIN}" "${SCRIPT_PATH}" \
		--run-mode "${RUN_MODE}" \
		--source-mode "${SOURCE_MODE}" \
		--ip-api-url "${IP_API_URL}" \
		--custom-ip-api-url "${CUSTOM_IP_API_URL}" \
		--cf-api-token "${CF_API_TOKEN}" \
		--cf-zone-id "${CF_ZONE_ID}" \
		--cf-dns-name "${CF_DNS_NAME}" \
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
		--cf-api-token "${CF_API_TOKEN}" \
		--cf-zone-id "${CF_ZONE_ID}" \
		--cf-dns-name "${CF_DNS_NAME}" \
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

