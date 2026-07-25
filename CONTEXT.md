# Domain Language

## Intent Compiler

A pre-execution control that turns a user's latest wording and bounded task context into an inspectable Intent Contract. It does not claim to recover a person's hidden or complete intention.

## Intent Contract

The typed statement of the proposed goal, operation, action owner, object, constraints, effects, data flow, authorization state, and unresolved slots for one action.

## Action Owner

The host, Skill, or memory capability responsible for performing the operation. Ownership is determined from the requested operation before object nouns are considered.

## Safety Gate

The deterministic decision that allows execution, requests a concrete approval, or blocks an action. A semantic model may raise risk but cannot lower this decision.

## Concrete Approval

Authorization bound to one action, its arguments, destination, and validity window. A short confirmation does not authorize unrelated or future actions.

## Decision Receipt

The user-visible summary of what the compiler understood, which capability it selected, which constraints remain active, and whether execution is allowed.

## Memory Evidence

Scoped, sourced, and revisable context that may support interpretation. Memory is never executable authority and cannot grant permissions.

## Semantic Adapter

An optional model-backed proposer for unfamiliar wording. Its output is untrusted input to the deterministic compiler.

## Host Enforcement

The host's act of calling the compiler before execution and honoring the resulting Safety Gate. Installation alone is not Host Enforcement.

## Benchmark Case

A versioned synthetic or consented request with preregistered expected control outcomes. A public Benchmark Case is a conformance test, not proof of population-level understanding.
