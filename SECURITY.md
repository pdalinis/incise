# Security policy

Security reports are welcome. Please report vulnerabilities privately so they can be investigated before details are made public.

## Supported versions

The project is in active development and has not yet established a stable release-support schedule. Until one is published, security fixes target the latest code on the default branch. Older commits and development snapshots may not receive patches.

## Reporting a vulnerability

Use GitHub private vulnerability reporting from the repository Security tab when it is available. Create a private report rather than a public issue or discussion.

If private vulnerability reporting is unavailable, contact the repository owner through GitHub without including exploit details and ask for a private reporting channel. Do not post sensitive reproduction material publicly.

## What to include

Include a clear description of the issue and its potential impact, the affected version or commit, a minimal reproduction or proof of concept, relevant platform and configuration details, and any suggested mitigation. State any disclosure constraints or requested attribution.

Remove credentials, private documents, and unrelated personal data. Use the smallest safe example that demonstrates the problem.

## What counts as a security issue

Security-relevant reports include unintended reads or writes outside the requested file, path traversal, command execution, unsafe handling across the CLI or plugin boundary, concurrency protections that can be bypassed, and behavior that can silently destroy unrelated user data despite the documented guards.

Ordinary correctness bugs, unsupported Markdown constructs, benchmark disagreements, and feature requests may be reported through the public issue tracker when they do not expose sensitive information or create a practical security risk.

## Response and disclosure

The maintainers will make a best-effort attempt to acknowledge a private report, assess its severity, and coordinate remediation and disclosure. Because the project is under active development, no fixed response or patch timeline is promised yet.

Please allow a reasonable remediation period before public disclosure. When a fix is ready, the project may publish an advisory describing affected versions, impact, mitigation, and credit if the reporter wants to be named.

## Good-faith research

Good-faith security research should avoid privacy violations, service disruption, destructive testing against data you do not own, and access beyond what is necessary to demonstrate the issue. Reports that follow these principles will be handled constructively.
