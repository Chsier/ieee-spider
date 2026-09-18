# Security Policy

## Supported Versions

Security fixes are applied to the current `main` branch.

## Reporting a Vulnerability

Use GitHub private security advisories for this repository:

1. Open the repository's **Security** tab.
2. Select **Advisories**.
3. Create a private vulnerability report.

Do not include credentials, cookies, browser storage state, private paper
files, or institution-specific configuration in a public issue.

## Credential and Session Handling

IEEE Spider is designed so that a human completes institutional SSO, MFA, and
CAPTCHA in a visible browser. The CLI does not store passwords.

The following runtime paths are untrusted and must never be committed:

```text
data/auth/
data/auth/browser-profile/
data/auth/ieee-storage-state.json
downloads/
config/authors.local.toml
config/login.local.toml
```

If a credential or session file is exposed, revoke the relevant account
session first, then remove the exposed material from Git history.

## Access-Control Policy

The project downloads only:

- open-access PDFs; or
- PDFs the authenticated account is entitled to access.

It must not be modified to bypass paywalls, DRM, CAPTCHA, MFA, entitlement
checks, or IEEE rate limits. Proxy use for access-control evasion is out of
scope and not supported.
