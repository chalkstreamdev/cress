# Security Policy

## Supported versions

cress is pre-1.0. Security fixes are applied to the latest released version only.

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Instead, report privately via GitHub's
[security advisories](https://github.com/chalkstreamdev/cress/security/advisories/new),
or email **nick@chalkstream.dev**.

Include a description of the issue, steps to reproduce, and the impact you've
identified. We'll acknowledge your report as soon as we can and keep you updated
on the fix.

## Scope notes

cress shells out to `git` and reads files from a vault and a target repo. It
delegates all git authentication to the user's existing git setup and never stores
credentials. Reports about credential handling, path traversal during attachment
resolution, or template injection are especially welcome.
