# Documentation

Explanation and procedure that outlives any one change. Code-adjacent `Readme.md` files
describe their directory; these pages describe the system.

- [`architecture/`](architecture/Readme.md), how the system is shaped and why
- [`operations/`](operations/Readme.md), running it: deploying, configuring, hosts, diagnosis
- [`development/`](development/Readme.md), changing it: navigation, checks, conventions, agents
- [`user-manual/`](user-manual/Readme.md), the product manual, for people using the site
- [`technical-specification/`](technical-specification/Readme.md), what the product does, stated once

Every page here is present-tense truth about the code that exists. Anything over about a
hundred lines opens with a table of contents.

**This tree is public.** No hostname, address, port identifying a real host, credential, or
description of an authentication boundary belongs in it. Those live in
`INFRASTRUCTURE_INVENTORY.md` at the repository root, which is local and gitignored, and
pages that need them name that path.
