# Security Policy

## Reporting a vulnerability

Please use GitHub Security Advisories on this repo. Private vulnerability reporting is enabled:

https://github.com/golikovichev/postman2pytest/security/advisories/new

Do not open a public issue for security reports. If GitHub advisories is unavailable to you, open a blank issue titled `security: contact` and I will move the conversation to a private channel.

I will reply within 5 working days. For confirmed issues the usual fix window is 30 days, sooner if the impact is high.

## Threat model

`postman2pytest` takes a Postman Collection v2.1 JSON file and emits a Python test module. Two surfaces matter:

1. The input JSON is untrusted user data. Field names, request URLs, body templates, header values come from a file the user supplies. The generator writes some of those values into the output Python source.
2. The output module is then executed by pytest in the user's environment.

A malicious collection could try to inject Python code into the generated module, or trick the user into running requests against an unexpected host. Reports about either path are welcome.

## In scope

- Code injection into the generated test file via crafted collection fields (URL, header name or value, body template, test script, variable name)
- Arbitrary file write outside the path passed to `--out`
- YAML or JSON parser issues that crash or hang on small inputs (resource exhaustion below 1 MB input)
- Leakage of environment variables or local files into the generated module

## Out of scope

- The generated tests hit a server the user pointed them at, that is expected behavior
- Collections that contain real credentials in plain text (collection authors should scrub before sharing)
- Issues in upstream packages (open a report on the dependency repo)

## Supported versions

The latest minor release on PyPI receives security fixes. Older minors do not.

## Credit

If you would like to be named in the advisory, say so in the report. Otherwise the fix lands quietly.
