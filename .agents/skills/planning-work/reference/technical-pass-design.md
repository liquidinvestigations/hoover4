# Technical design for an implementation package

Scale detail to the change. A local correction can describe its behavior in the package.
A change shared across passes needs one linked design.

Identify the current defect and the intended observable result.
Name the source owner, callers, data shape, algorithm, and error behavior that must change.
Describe ordering, idempotency, cancellation, and compatibility where those contracts apply.
Name the old paths that become unnecessary and the conditions for removing them.

For persistent data, state how old records remain readable and how new writes are identified.
For workflow changes, state how active histories remain executable during deployment.
For shared Python and Rust behavior, name both consumers and the common acceptance cases.

Define verification before implementation.
Include the original failure and relevant boundary cases.
Distinguish unit evidence, service integration, browser interaction, and model behavior.

Ask about unresolved material requirements. Choose ordinary implementation details within the accepted design.
Do not schedule another architecture review merely because the document exists.
Use independent review when the change's risk or the person requires it.
