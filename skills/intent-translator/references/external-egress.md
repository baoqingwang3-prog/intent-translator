# External Egress

Apply this protocol before sending user-derived context to web search, cloud models, remote MCP servers, issue trackers, messaging systems, or other external services.

## Gate

1. Confirm that external transmission is required for the requested outcome.
2. Run `scripts/privacy_guard.py --redact` on the smallest sufficient context when practical.
3. Block transmission of credentials, private keys, authentication codes, payment data, or similarly dangerous material.
4. Replace personal identifiers with roles or placeholders unless identity is necessary and authorized.
5. Generalize confidential numbers into ranges when exact values are unnecessary.
6. Send only the redacted minimum and keep source material local.

The scanner detects common patterns; it cannot identify every name, trade secret, medical detail, or context-specific sensitivity. Agent review remains required.

Do not treat permission to search as permission to upload an entire file, profile, memory database, or conversation history.
