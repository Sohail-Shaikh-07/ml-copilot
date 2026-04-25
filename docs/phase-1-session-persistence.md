# Phase 1 Session Persistence

This document captures the session persistence slice for `ML Copilot`.

## Task

`ML-7 / Implement persistent sessions messages and events`

## Scope

This slice builds on the SQLite schema by adding the higher-level repository
operations needed for real session persistence:

- update stored session metadata and status
- load full session history in one call
- list events after a known sequence for replay-style access
- delete sessions cleanly through the root record

## Why This Shape

The schema alone is not enough for the next backend and agent-loop tasks. They
need storage operations that feel like session primitives rather than raw table
inserts.

That lets later work focus on behavior instead of re-implementing persistence
queries in multiple places.

## Notes

This still keeps persistence in one explicit repository. The next steps can now
build replay, routes, and agent history handling on top of a stable storage API.
