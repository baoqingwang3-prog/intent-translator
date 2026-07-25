# Security Policy

## Supported Versions

Security fixes are applied to the latest Alpha release and the current `main` branch. Older Alpha tags are immutable historical releases and may not receive backports.

## Report A Vulnerability

Use the repository's private [GitHub Security Advisory](https://github.com/baoqingwang3-prog/intent-translator/security/advisories/new) form. Do not open a public issue for a suspected secret leak, authorization bypass, private-data exposure, receipt replay, installer compromise, or cross-profile contamination.

Include the affected version, operating system, host, minimal reproduction, expected control decision, actual decision receipt, and whether private data may have left the device. Redact credentials, exact home paths, private profile text, and identifying utterances.

The maintainers will acknowledge a complete report, reproduce it where possible, classify the affected trust boundary from [docs/threat-model.md](docs/threat-model.md), and publish a remediation note after users have a reasonable opportunity to update.

## Scope Limits

This project cannot enforce safety when a host does not call the preflight or ignores its result. Vulnerabilities in downstream Agents, Skills, browsers, operating systems, and external services should also be reported to their respective maintainers.
