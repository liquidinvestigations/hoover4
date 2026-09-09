# Shared capture-login resolution. Source after LOGIN_ENV_FILE is set.
# Sets CRED_USERNAME, CRED_PASSWORD, CRED_SOURCE.
# Exports HOOVER4_TEST_USERNAME and HOOVER4_TEST_PASSWORD when a pair is present.
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
