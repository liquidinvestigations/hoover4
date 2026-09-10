# Shared capture-login resolution. Source after LOGIN_ENV_FILE is set.
# Sets CRED_USERNAME, CRED_PASSWORD, CRED_SOURCE.
# Exports HOOVER4_TEST_USERNAME and HOOVER4_TEST_PASSWORD when a pair is present.
# Exports HOOVER4_SITE_URL from the login-env file when the environment does not set it.
# Defines require_capture_target, which exits 2 when --target and HOOVER4_SITE_URL are both empty.
# Credential values never appear in this file's arguments.

read_login_env_value() {
    local file="$1" key="$2" raw
    [ -n "$file" ] && [ -f "$file" ] || return 0
    raw="$(sed -n "s/^${key}=//p" "$file" | tail -n1)"
    raw="${raw%$'\r'}"
    if [[ "$raw" == \'*\' || "$raw" == \"*\" ]]; then
        raw="${raw:1:-1}"
    fi
    printf '%s' "$raw"
}

CRED_USERNAME=""
CRED_PASSWORD=""
CRED_SOURCE=""
if [ -n "${HOOVER4_TEST_USERNAME:-}" ] || [ -n "${HOOVER4_TEST_PASSWORD:-}" ]; then
    CRED_USERNAME="${HOOVER4_TEST_USERNAME:-}"
    CRED_PASSWORD="${HOOVER4_TEST_PASSWORD:-}"
    CRED_SOURCE="the HOOVER4_TEST_USERNAME/HOOVER4_TEST_PASSWORD environment variables"
else
    FILE_USER="$(read_login_env_value "$LOGIN_ENV_FILE" HOOVER4_TEST_USERNAME)"
    FILE_PASS="$(read_login_env_value "$LOGIN_ENV_FILE" HOOVER4_TEST_PASSWORD)"
    if [ -n "$FILE_USER" ] || [ -n "$FILE_PASS" ]; then
        CRED_USERNAME="$FILE_USER"
        CRED_PASSWORD="$FILE_PASS"
        CRED_SOURCE="$LOGIN_ENV_FILE"
    fi
fi

if [ -n "$CRED_USERNAME" ] && [ -z "$CRED_PASSWORD" ]; then
    echo "error: a username with no password is a validation failure (source: $CRED_SOURCE)" >&2
    exit 2
fi
if [ -z "$CRED_USERNAME" ] && [ -n "$CRED_PASSWORD" ]; then
    echo "error: a password with no username is a validation failure (source: $CRED_SOURCE)" >&2
    exit 2
fi

if [ -n "$CRED_USERNAME" ]; then
    export HOOVER4_TEST_USERNAME="$CRED_USERNAME"
    export HOOVER4_TEST_PASSWORD="$CRED_PASSWORD"
fi

# HOOVER4_SITE_URL from the login-env file when the environment does not already set it.
SITE_URL_SOURCE=""
if [ -n "${HOOVER4_SITE_URL:-}" ]; then
    SITE_URL_SOURCE="the HOOVER4_SITE_URL environment variable"
else
    FILE_SITE="$(read_login_env_value "$LOGIN_ENV_FILE" HOOVER4_SITE_URL)"
    if [ -n "$FILE_SITE" ]; then
        export HOOVER4_SITE_URL="$FILE_SITE"
        SITE_URL_SOURCE="$LOGIN_ENV_FILE"
    fi
fi

require_capture_target() {
    if [ -n "${TARGET_ARG:-}" ]; then
        SITE_URL="$TARGET_ARG"
        TARGET_SOURCE="--target"
        return 0
    fi
    if [ -n "${HOOVER4_SITE_URL:-}" ]; then
        SITE_URL="$HOOVER4_SITE_URL"
        TARGET_SOURCE="${SITE_URL_SOURCE:-the HOOVER4_SITE_URL environment variable}"
        return 0
    fi
    echo "error: no capture target. Pass --target URL, or set HOOVER4_SITE_URL in the environment or in the login-env file." >&2
    echo "       (checked --target, HOOVER4_SITE_URL, ${LOGIN_ENV_FILE:-no login-env file})" >&2
    exit 2
}
