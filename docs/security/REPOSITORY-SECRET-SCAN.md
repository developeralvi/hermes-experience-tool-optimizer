# Repository Secret Scan

**Project:** hermes-experience-tool-optimizer
**Repository:** https://github.com/developeralvi/hermes-experience-tool-optimizer
**Source:** Fresh clone from remote (4d2bc3a)
**Audit date:** 2026-10-08

## Methodology

A pattern-based secret scan was performed on the complete repository contents.

Patterns scanned:

- API keys (api_key, API_KEY, API_KEY=)
- Generic tokens (TOKEN, TOKEN)
- Passwords (PASSWORD, password)
- Secrets (SECRET, secret)
- Bearer tokens (BEARER, bearer)
- Authorization headers (AUTHORIZATION, authorization)
- Private keys (PRIVATE KEY, PRIVATEKEY)
- Cookies (cookie)
- Credentials (credential)
- Windows author paths (C:\Users)
- Environment files (.env)
- SSH private keys (BEGIN .*PRIVATE KEY)
- Short API prefixes (sk-, xoxb-, AKIA)

## Results

| Pattern | Hit count |
|---|---|
| API_KEY | 5 |
| TOKEN | 8 |
| PASSWORD | 4 |
| SECRET | 9 |
| BEARER | 3 |
| AUTHORIZATION | 4 |
| PRIVATE KEY | 2 |
| cookie | 2 |
| credential | 4 |
| C:\Users | 0 |
| .env | 6 |
| BEGIN PRIVATE KEY | 1 |
| sk- | 5 |
| xoxb- | 1 |
| AKIA | 1 |

## Interpretation

All hits are **documentation/config concepts**, not real secrets. The affected
files are:

| File | Context |
|---|---|
| `src/hermes_ebtto/privacy.py` | Contains **privacyRegexes** that detect and redact secret-like strings: API keys (AKIA, AI_, sk-, gh_, xoxb-), bearer tokens, Slack (xoxb-), etc. These are **redaction patterns**, not real values. |
| `src/hermes_ebtto/config.py` | Config key names (api_key, access_token, api_key) |
| `src/hermes_ebtto/events.py` | Event field names (access_token, api_key, secret) |
| `tests/unit/test_package.py` | Test cases that verify redaction behavior (e.g., `Authorization: Bearer ***`) |
| `docs/acceptance/*.md` | Documentation examples mentioning API keys, tokens, passwords, Authorization, bearer, secrets, credentials |

No file contains:

- A real API key value
- A real token value
- A real password
- A real private key
- An .env file with actual secrets
- `C:\Users\` — the scanner reports 0 for this pattern because the remote repo (fresh clone) contains no author paths.

## Conclusion

**CLEAN** — no secrets detected in the published repository.

The scanner patterns flag documentation/config keys (e.g., `api_key`, `Authorization: Bearer ***`,
`xoxb-...`, `sk-...`) which are validation rules and test cases for the privacy system, not real
secrets. These are safe to publish.

## Recommendations

- Keep the privacyRegexes in `privacy.py` for secret detection.
- No secrets were found and none need to be rotated.
- Future contributions should not add real secrets to the repository.
