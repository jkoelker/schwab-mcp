# Security Policy

`schwab-mcp` can read brokerage accounts and, when write tools are enabled,
place orders. Please report security problems privately.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: open the repository's
**Security** tab and choose **Report a vulnerability**. Do not open a public
issue, pull request, or discussion for a suspected vulnerability.

Include what you found, how to reproduce it (with mocks or a paper account,
never someone else's credentials), and the commit you tested.

## Scope

In scope: the order approval flow (what a reviewer sees versus what is
placed), input validation, the HTTP transport, token and credential storage,
the container image, and the packaging and CI configuration in this
repository.

Out of scope: vulnerabilities in Schwab's API, Discord, Signal, or upstream
libraries; report those to their maintainers.
