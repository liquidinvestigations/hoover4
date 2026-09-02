# Single sign-on

What a deployment must put in front of hoover4 for a person to reach it.

## The proxy is the only way in

hoover4 mints no session of its own. Every route requires an already-resolved identity,
except `/favicon.ico`. The identity comes from a session cookie already in `web_sessions`,
or from four headers a reverse proxy asserts on the request. A caller with neither gets a
`401` response from every other route.

The reverse proxy sits in front of the website and terminates every connection. Nothing
reaches hoover4 by another path.

## The four headers

| header | required | format |
|---|---|---|
| `X-Forwarded-User` | yes | the username, trimmed. A missing or blank value gets a `401` response |
| `X-Forwarded-Preferred-Username` | no | the display name, trimmed. An absent header gives an empty string |
| `X-Forwarded-Email` | no | the email address, trimmed. An absent header gives an empty string |
| `X-Forwarded-Groups` | no | a comma-separated list. Each entry is trimmed, an empty entry is dropped, and a repeated entry is kept once |

A header name is read case-insensitively.

## The administrator condition

A person is an administrator when `X-Forwarded-Groups` carries the literal string `admin`
or the literal string `superuser`. No other group name grants it.

## This project's implementation

This project puts `liquid-core` behind `oauth2-proxy` to produce the four headers.
`liquid-core` sets no identity header itself. It publishes identity as JSON at
`/accounts/profile` and as OIDC claims. `oauth2-proxy` turns one of those into the headers
above. `liquid-core` puts the literal strings `admin` and `superuser` into its `roles` list
for a staff user and a superuser. The administrator condition matches without a code change
on either side.

Any proxy that asserts the same four headers, in the same format, works in place of this
pair.

## Known limitation: sign-out

`liquid-core` clears a downstream application's proxy session from a shared Redis store,
keyed by an application id, when a person signs out. hoover4 keeps its own session table
and its own cookie, which that mechanism cannot see. A person who signs out of
`liquid-core` keeps a hoover4 session until it expires on its own.
