# Week 3 — AI Code Review
 
Reviewed by: ChatGPT Codex    Date: 03/11/2026
 
## Findings
 
| # | File:line | What it says is wrong | Is it real? | Action |
|---|---|---|---|---|
| 1 | app/__init__.py: 15 | Default secret can be used in production. app/__init__.py only rejects the default key when FLASK_ENV equals production, while [app/config.py (line 8)] supplies that key when SECRET_KEY is unset. | Yes | To be fixed |
| 2 | .gitignore: 1 and .dockerignore: 1 | Environment file is not excluded from Git or Docker builds. | Yes | Fixed |
| 3 | app/blueprints/tutor.py:433 | Tutors can see attendance totals for classes they cannot access. | No | Ignored |
| 4 | app/__init__.py:19 | Forwarded headers are trusted from any request source. | Yes | To be fixed |
| 5 | app/blueprints/tutor.py:89 | Invalid class dates can produce a server error. | Yes | Fixed |

 
## What I fixed, and why
Fixed 2 as it was a simple fix.
Fixed 5 as it was also a simple fix. 
 
## What I am knowingly leaving, and why
1. This is ok for the development version, will come back to it after the initial basic version is up and running. 
3. Ignoring this as it's not an issue.
4. Will leave this for now as I need to investigate more. Fine to leave as is for local development version. 
 
## What the reviewer got wrong
Nothing wrong, all flagged issues were valid. 