# Phase 1 Persistence

This document captures the persistence slice for `ML Copilot`.

## Task

`ML-6 / Design SQLite schema and repository layer`

## Scope

This slice adds a stdlib SQLite persistence layer with:

- schema creation for sessions, messages, events, tool calls, approvals, and eval runs
- dataclass records for the main persisted entities
- a repository API for sessions, messages, and events
- timestamp updates on session activity

## Why This Shape

The repository layer stays intentionally small for now:

- enough to persist session history
- enough to support replay and debugging later
- enough to stabilize the schema before route and agent-loop work lands

That gives later tasks a clean place to build:

- event replay
- approval storage
- agent turn persistence
- eval reporting

## Notes

This uses `sqlite3` from the standard library to keep the persistence layer easy
to inspect and easy to test. We can move to migrations or a heavier ORM later if
the project grows enough to justify that complexity.
