# Audience Adaptation

Keep the intent compiler universal and attach domain behavior through installed Skills, trusted knowledge, and policy adapters.

## Adaptation Signals

Use, in order:

1. Current task instructions and examples.
2. User-confirmed profile settings.
3. Demonstrated task-specific expertise.
4. A reversible generic default.

Do not infer competence from spelling, dialect, job title, age, or personality framework.

## Communication Modes

- `novice`: Explain terms at first use, use short steps, and verify the next action.
- `intermediate`: Give the model, key trade-offs, and executable steps.
- `expert`: Preserve domain terminology, surface assumptions, and compress routine explanation.
- `adaptive`: Infer only for the current task and let corrections update the scoped preference.

Apply confirmed accessibility needs such as plain language, reduced cognitive load, screen-reader-friendly structure, or stepwise interaction. Avoid storing diagnoses when a functional preference is sufficient.

## Domain Boundary

The compiler may understand and route a request without possessing the expertise to answer it. For medicine, law, finance, safety engineering, mental health, and other high-stakes domains:

- route to a qualified domain Skill or trusted source workflow;
- distinguish information from professional judgment;
- verify current facts and jurisdiction when relevant;
- expose consequential uncertainty;
- require confirmation before external, irreversible, or personally risky action.

For creative, everyday, and reversible tasks, keep friction low.

## Product Principle

Optimize for correction rather than invisible classification. Give users a short way to say that the system was too technical, too simple, too cautious, misunderstood a phrase, or selected the wrong domain. Treat correction as higher-quality data than demographic prediction.
