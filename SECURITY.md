# Security Policy

## Reporting

Do not open a public issue containing a credential, private memory database, personal profile, or exploit payload with sensitive data. Report security problems privately to the repository owner through GitHub's private vulnerability reporting when enabled.

## Data Boundary

The default memory and profile paths are local and excluded from version control. This repository must not contain real user profiles, memory databases, tokens, private keys, authentication codes, payment data, or private machine paths.

The privacy scanner is a pattern-based guard, not a complete data-loss-prevention system. Review context before external transmission, especially when it contains health, financial, identity, employment, legal, or confidential business information.

## Supported Versions

Until the first stable release, only the latest commit on the default branch receives security fixes.
