# Security Policy

## Reporting a vulnerability

Do not open a public issue for security reports. Use GitHub's private vulnerability reporting form:

https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/security/advisories/new

I try to acknowledge new reports within 7 days and aim for an initial assessment within 14 days. There is no bug bounty.

## Scope

whyknot-yt-dlp-plugins is a Python yt-dlp plugin package. Reports are in scope when they involve unintended code execution, unsafe file writes, privilege boundary issues, local service exposure, or behavior that lets untrusted input compromise the user's machine or project.

Functional bugs, compatibility problems, false positives, and upstream dependency issues should be filed as normal issues unless they have a concrete security impact.