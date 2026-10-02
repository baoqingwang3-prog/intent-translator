# PR 16 integration

The compiler keeps a newly requested local edit or compression after a veto of
old work, asks for missing references, and distinguishes recall, teaching,
compression, local lookup, public lookup, and quoted source content.

The integration starts from main `bd4be06` and retains its actor-bound persistent
receipts, control identities, host hooks, decision logs, unknown-action checks,
and non-local destination checks. Semantic `clarify` and `revoke` stop execution
before a receipt is consumed. A memory label cannot authorize an unknown action;
only a complete, nominalized record instruction can bypass the unclassified
imperative check. The effective final helper definitions carry the new behavior.

All optional scripts, datasets, and historical results from PR head `f0b6a86`
are retained. These development tools do not enable a semantic provider or
install a host runtime. Their model dependencies remain optional.

## Optional model tools

Use a separate development environment with `fastembed==0.8.0` and a compatible
cached model. Set `ILANG_DISTILL_DEPS` to that environment's package directory,
`ILANG_DISTILL_EMBED_MODEL` to the model name, and `ILANG_DISTILL_MODEL_PATH` to
the cache directory when required. `ILANG_DISTILL_OFFLINE=1` prevents downloading
a model during the checks. The standard CI tests use fake model encoders and
do not establish population-level model accuracy.

`start_semantic_server.cmd` accepts `ILANG_SEMANTIC_PYTHON`, defaults to Python on
PATH, respects configured model settings, and forwards server arguments. The
server continues to listen on loopback by default.

Run the frozen development regression with explicit, portable paths:

```text
python scripts/dev_regression_v3.py --audit-dir <frozen-audit-directory> --semantic-python <python-executable> --output <new-result-path>
```

The audit directory must contain the unchanged fixture, scorer, and freeze
manifest. The fixture hash and scoring thresholds are unchanged. Existing
result files are rejected rather than overwritten. The output remains marked
`acceptance: false`; a successful process exit is not independent acceptance.

`ilang_step3_acceptance.py` checks the older 204-case held-out proposal contract.
Its revocation expectations predate `control_status`; its failures must be
reported, not hidden by changing the dataset or weakening its mode checks.
Historical JSON/TXT scores are provenance, not evidence for the integrated tree.
With the cached E5 model and `fastembed==0.8.0`, the integrated and original PR
proposal checks both pass 188 of 204 cases with the same 16 failures. This is
baseline parity, not a passed held-out acceptance gate.
