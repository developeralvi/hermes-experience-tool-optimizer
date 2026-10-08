# EBTTO Security Policy

**Experience-Based Tool Trajectory Optimization (EBTTO)** handles live tool-call
trajectories from the Hermes Agent runtime. This document defines how security
vulnerabilities should be reported and handled.

---

## 1. Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## 2. Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please
**do not open a public issue**.

**Report privately via:**
- GitHub Security Advisories on this repository
- Email: security@ebtto.social (if established)

Please include:
- A clear description of the vulnerability
- Steps to reproduce
- The impact of the vulnerability
- Any potential fixes you have identified

## 3. Scope

### In scope
- Secret leakage (API keys, tokens, credentials in trajectories)
- Path traversal in trajectory storage paths
- Prompt injection via tool results
- Poisoned historical experience (malicious retrieved guidance)
- Unsafe trajectory replay (executing stored historical calls)
- Database corruption or privilege escalation

### Out of scope
- Denial of service against exogenous model providers
- Bugs in the upstream Hermes Agent runtime
- Vulnerabilities requiring physical access

## 4. Trust Model

EBTTO treats historical experience as **untrusted data**.

Experience is stored as evidence, not as permission. The system **never automatically
executes** historical trajectories. Retrieved guidance is advisory, and only the
controlled auto mode requires explicit user opt-in for auto-execution.

## 5. Secret Handling

- **Never store raw secrets** in trajectories. All tool arguments and results
  are sanitized before database persistence.
- Redaction patterns match `Authorization: Bearer ***`, `xoxb-`, `sk-`,
  `AKIA*`, private key headers, etc.
- Export tools (benchmark, trajectory export) sanitize before output.

## 6. Vulnerability Response

| Status | Policy |
|--------|--------|
| Confirmed | Fixed in next minor release |
| Proven | Backported to latest minor |
| Denied | Closed with rationale |

We follow a 90-day disclosure window for confirmed vulnerabilities.

## 7. Security Contact

For security issues, do not use the public issue tracker.

---

*This policy is a living document. Update it as the project's security posture matures.*
