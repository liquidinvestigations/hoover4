# Supply request identity through the configured provider.

[Session middleware](../../website/backend/src/auth/session_middleware.rs) resolves request identity.
[The route policy](../../website/backend/src/auth/route_policy.rs) requires identity on every route except `/favicon.ico`.
Website routes do not create sessions.
An existing session cookie can resume an unexpired row already stored in `web_sessions`.
Deployment access details belong in the private infrastructure inventory.

## Supply the identity headers.

| Header | Requirement | Format |
|---|---|---|
| `X-Forwarded-User` | The header identity requires a nonempty username. | The middleware trims surrounding whitespace. |
| `X-Forwarded-Preferred-Username` | This header is optional. | It supplies the display name, or an empty string when absent. |
| `X-Forwarded-Email` | This header is optional. | It supplies the email address, or an empty string when absent. |
| `X-Forwarded-Groups` | This header is optional. | It supplies comma-separated groups. The middleware trims, deduplicates, and removes empty entries. |

Header names are case-insensitive.
The deployment must supply headers through its configured identity integration.
Keep the selected provider, traffic path, and access boundary in the private inventory.
[Deployment configuration](Configuration_Reference.md) describes the available keys and generated service configuration.

## Resolve administrator and collection permissions.

The middleware recognizes the exact group values `admin` and `superuser` for administrator identity.
Other groups receive collection access through stored grants.
[Permission checks](../../website/backend/src/auth/permissions.rs) restrict each collection read.
[The administration manual](../user-manual/Admin_Manual.md#users-and-groups) explains group management.

## Verify sign-in and sign-out behavior.

Verify the identity returned by `whoami` through the configured provider.
Verify ordinary and administrator access with their respective accounts.
Calling `whoami` reads identity and does not create a session.
An existing website session cookie follows its stored expiration and deletion state.
Do not assume that an external provider's sign-out also deletes an existing website session row.
Verify that behavior in the actual integration before documenting its result.

## Use the separate agent identity contract.

Agent routes use their own request identity contract in the same middleware.
Do not copy browser identity handling into an agent caller.
[The agent API](../../website/backend/src/api/agent/) defines its typed routes and collection checks.
