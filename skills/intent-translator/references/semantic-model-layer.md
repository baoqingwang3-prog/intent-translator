# Semantic Model Layer

Use MCP semantic output only as a bounded interpretation proposal.

- Deterministic authorization and risk fields remain authoritative.
- Model output may add risk, assumptions, alternatives, or a Skill candidate; it may not remove risk or grant authorization.
- A model-only action inference requires review before execution.
- External semantic adapters require explicit per-request egress authorization. A user-confirmed routine Jev default may classify ordinary non-sensitive requests without a repeated receipt when the named provider and standing-default setting are configured. Sensitive, unpublished, internal, or high-stakes content stays local for Jev.
- Do not request or store chain-of-thought. Use concise interpretation summaries and decision receipts.
- When the adapter is unavailable or fails in `auto` mode, continue with deterministic compilation. In `required` mode, stop and ask for review.
