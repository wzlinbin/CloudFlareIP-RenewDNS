#!/bin/sh
set -eu

uci_get() {
	uci -q get "cfip.main.$1" 2>/dev/null || true
}

to_int() {
	v="$1"
	d="$2"
	case "$v" in
		''|*[!0-9]*) echo "$d" ;;
		*) echo "$v" ;;
	esac
}

clamp() {
	v="$1"
	min="$2"
	max="$3"
	if [ "$v" -lt "$min" ]; then
		echo "$min"
		return
	fi
	if [ "$v" -gt "$max" ]; then
		echo "$max"
		return
	fi
	echo "$v"
}

ENABLED="$(uci_get enabled)"
SCHEDULE_MODE="$(uci_get schedule_mode)"
SCHEDULE_HOUR="$(to_int "$(uci_get schedule_hour)" 3)"
SCHEDULE_WEEKDAY="$(to_int "$(uci_get schedule_weekday)" 1)"
SCHEDULE_MONTHDAY="$(to_int "$(uci_get schedule_monthday)" 1)"

[ -n "${ENABLED}" ] || ENABLED="0"
[ -n "${SCHEDULE_MODE}" ] || SCHEDULE_MODE="daily"
SCHEDULE_HOUR="$(clamp "${SCHEDULE_HOUR}" 0 23)"
SCHEDULE_WEEKDAY="$(clamp "${SCHEDULE_WEEKDAY}" 0 6)"
SCHEDULE_MONTHDAY="$(clamp "${SCHEDULE_MONTHDAY}" 1 31)"

CRON_FILE="/etc/crontabs/root"
TMP_FILE="/tmp/cfip-cron.$$"
TAG="# cfip-lite-schedule"
CMD="/usr/libexec/cfip/run.sh >/tmp/cfip-lite.log 2>&1"

[ -f "${CRON_FILE}" ] || touch "${CRON_FILE}"
grep -v "${TAG}" "${CRON_FILE}" > "${TMP_FILE}" || true

if [ "${ENABLED}" = "1" ]; then
	case "${SCHEDULE_MODE}" in
		weekly)
			LINE="0 ${SCHEDULE_HOUR} * * ${SCHEDULE_WEEKDAY} ${CMD} ${TAG}"
			;;
		monthly)
			LINE="0 ${SCHEDULE_HOUR} ${SCHEDULE_MONTHDAY} * * ${CMD} ${TAG}"
			;;
		*)
			LINE="0 ${SCHEDULE_HOUR} * * * ${CMD} ${TAG}"
			;;
	esac
	echo "${LINE}" >> "${TMP_FILE}"
fi

mv "${TMP_FILE}" "${CRON_FILE}"

if [ -x /etc/init.d/cron ]; then
	/etc/init.d/cron restart >/dev/null 2>&1 || /etc/init.d/cron reload >/dev/null 2>&1 || true
fi

