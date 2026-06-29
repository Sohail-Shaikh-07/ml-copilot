"""Bootstrap entrypoint for the ML Copilot application."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from app.agent.loop import create_agent_loop
from app.config import AppSettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ml-copilot",
        description="Focused ML engineering agent for repository analysis and safe automation.",
    )
    parser.add_argument(
        "--print-layout",
        action="store_true",
        help="Print the expected repository layout for the current bootstrap slice.",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print the effective runtime configuration with sensitive values redacted.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Chat command - interactive chat
    chat_parser = subparsers.add_parser("chat", help="Start an interactive chat session")
    chat_parser.add_argument(
        "--session",
        type=str,
        help="Resume an existing session by ID",
    )
    chat_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="LLM model to use (default: from config)",
    )

    # Run command - single analysis task
    run_parser = subparsers.add_parser("run", help="Run a single analysis task")
    run_parser.add_argument(
        "prompt",
        nargs="...",
        help="The task prompt to execute",
    )
    run_parser.add_argument(
        "--session",
        type=str,
        help="Session ID to use (default: create new)",
    )
    run_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="LLM model to use (default: from config)",
    )
    run_parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming output",
    )

    # Sessions command - list sessions
    _ = subparsers.add_parser("sessions", help="List all sessions")

    # Resume command - resume a session
    resume_parser = subparsers.add_parser("resume", help="Resume a session")
    resume_parser.add_argument(
        "session_id",
        type=str,
        help="Session ID to resume",
    )
    resume_parser.add_argument(
        "--prompt",
        type=str,
        help="Optional new prompt to send",
    )

    approvals_parser = subparsers.add_parser("approvals", help="List pending tool approvals")
    approvals_parser.add_argument(
        "--session",
        type=str,
        help="Filter pending approvals to a single session",
    )

    approve_parser = subparsers.add_parser("approve", help="Approve a pending tool call")
    approve_parser.add_argument("approval_id", type=str, help="Approval ID to approve")
    approve_parser.add_argument(
        "--session",
        type=str,
        required=True,
        help="Session ID that owns the approval",
    )
    approve_parser.add_argument(
        "--feedback",
        type=str,
        help="Optional feedback to persist with the approval decision",
    )
    approve_parser.add_argument(
        "--edited-args",
        type=str,
        help="Optional JSON object to replace the tool arguments before execution",
    )

    reject_parser = subparsers.add_parser("reject", help="Reject a pending tool call")
    reject_parser.add_argument("approval_id", type=str, help="Approval ID to reject")
    reject_parser.add_argument(
        "--session",
        type=str,
        required=True,
        help="Session ID that owns the approval",
    )
    reject_parser.add_argument(
        "--feedback",
        type=str,
        help="Optional feedback to persist with the rejection",
    )

    eval_parser = subparsers.add_parser("eval", help="Run a fixture-based evaluation")
    eval_parser.add_argument(
        "fixture",
        type=Path,
        help="Path to an eval fixture JSON file or a directory of fixture JSON files",
    )
    eval_parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for eval workspaces and artifacts (default: .ml-copilot/evals)",
    )
    eval_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the persisted eval report JSON instead of a short summary",
    )

    return parser


def format_layout(settings: AppSettings) -> str:
    paths = settings.paths
    return "\n".join(
        [
            "ML Copilot bootstrap is ready.",
            f"workspace_root={paths.workspace_root}",
            f"app_dir={paths.app_dir}",
            f"tests_dir={paths.tests_dir}",
            f"docs_dir={paths.docs_dir}",
            f"scripts_dir={paths.scripts_dir}",
        ]
    )


def format_config(settings: AppSettings) -> str:
    redacted_api_key = "<unset>" if settings.llm.api_key is None else "<redacted>"
    return "\n".join(
        [
            "ML Copilot configuration",
            f"workspace_root={settings.paths.workspace_root}",
            f"db_path={settings.db_path}",
            f"llm.base_url={settings.llm.base_url}",
            f"llm.model={settings.llm.model}",
            f"llm.api_key={redacted_api_key}",
            f"llm.timeout_seconds={settings.llm.timeout_seconds}",
            f"safety.require_tool_approval={settings.safety.require_tool_approval}",
            f"safety.allow_destructive_commands={settings.safety.allow_destructive_commands}",
            f"safety.redact_secrets={settings.safety.redact_secrets}",
            f"mcp.enabled={settings.mcp.enabled}",
            f"mcp.manifest_path={settings.mcp.manifest_path or '<unset>'}",
        ]
    )


async def run_analysis(loop, session, prompt: str, stream: bool = True) -> None:
    """Run a single analysis task."""
    result = await loop.run_turn(
        session=session,
        user_message=prompt,
        system_prompt=None,
    )
    print(f"\n[Result] Status: {result['status']}, Iterations: {result['iterations']}")
    if result.get("content"):
        print(f"\n[Response]\n{result['content']}")


async def run_chat(loop, session) -> None:
    """Run an interactive chat session."""
    print("ML Copilot Chat Mode")
    print("Type your messages. Press Ctrl+C to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "/exit"):
                break

            result = await loop.run_turn(
                session=session,
                user_message=user_input,
            )
            print(f"\n[Status] {result['status']}\n")

        except KeyboardInterrupt:
            print("\nExiting chat mode.")
            break
        except Exception as e:
            print(f"Error: {e}")


async def list_sessions(repository) -> None:
    """List all sessions."""
    sessions = repository.list_sessions()
    if not sessions:
        print("No sessions found.")
        return

    print(f"{'Session ID':<40} {'Title':<30} {'Status':<10} {'Created':<30}")
    print("-" * 110)
    for s in sessions:
        title = s.title or "(no title)"
        print(f"{s.id:<40} {title[:28]:<30} {s.status:<10} {s.created_at:<30}")


async def list_pending_approvals(repository, session_id: str | None = None) -> None:
    """List pending tool approvals."""
    pending = repository.list_pending_approvals(session_id)
    if not pending:
        print("No pending approvals found.")
        return

    print(f"{'Approval ID':<40} {'Session ID':<40} {'Tool':<20} {'Requested'}")
    print("-" * 130)
    for item in pending:
        print(
            f"{item.approval.id:<40} {item.approval.session_id:<40} "
            f"{item.tool_call.tool_name:<20} {item.approval.requested_at}"
        )
        print(f"  arguments={item.tool_call.arguments_json}")


async def cmd_run(args: argparse.Namespace, settings: AppSettings) -> int:
    """Execute the 'run' command."""
    # Combine prompt arguments
    prompt = " ".join(args.prompt) if args.prompt else ""
    if not prompt:
        print("Error: No prompt provided. Use 'ml-copilot run \"your task\"'")
        return 1

    # Create agent loop
    loop = create_agent_loop(settings)

    # Create or resume session
    if args.session:
        session = loop.repo.get_session(args.session)
        if not session:
            print(f"Error: Session {args.session} not found")
            return 1
    else:
        session = loop.repo.create_session(
            model=args.model or settings.llm.model,
            title=prompt[:50],
        )
        print(f"Created session: {session.id}")

    # Run analysis
    await run_analysis(loop, session, prompt, stream=not args.no_stream)

    # Update session status
    loop.repo.update_session(session.id, status="idle")

    return 0


async def cmd_chat(args: argparse.Namespace, settings: AppSettings) -> int:
    """Execute the 'chat' command."""
    loop = create_agent_loop(settings)

    if args.session:
        session = loop.repo.get_session(args.session)
        if not session:
            print(f"Error: Session {args.session} not found")
            return 1
        print(f"Resuming session: {session.id}")
    else:
        session = loop.repo.create_session(
            model=args.model or settings.llm.model,
            title="Interactive Chat",
        )
        print(f"Created session: {session.id}")

    await run_chat(loop, session)
    return 0


async def cmd_sessions(args: argparse.Namespace, settings: AppSettings) -> int:
    """Execute the 'sessions' command."""
    repo = asyncio.run(asyncio.to_thread(lambda: _get_sync_repo(settings)))
    await list_sessions(repo)
    return 0


async def cmd_resume(args: argparse.Namespace, settings: AppSettings) -> int:
    """Execute the 'resume' command."""
    loop = create_agent_loop(settings)

    session = loop.repo.get_session(args.session_id)
    if not session:
        print(f"Error: Session {args.session_id} not found")
        return 1

    print(f"Resuming session: {session.id}")

    if args.prompt:
        await run_analysis(loop, session, args.prompt)
    else:
        await run_chat(loop, session)

    return 0


async def cmd_approvals(args: argparse.Namespace, settings: AppSettings) -> int:
    """Execute the 'approvals' command."""
    repo = _get_sync_repo(settings)
    await list_pending_approvals(repo, args.session)
    return 0


async def cmd_approve(args: argparse.Namespace, settings: AppSettings) -> int:
    """Execute the 'approve' command."""
    loop = create_agent_loop(settings)
    session = loop.repo.get_session(args.session)
    if not session:
        print(f"Error: Session {args.session} not found")
        return 1

    edited_arguments = None
    if args.edited_args:
        try:
            parsed = json.loads(args.edited_args)
        except json.JSONDecodeError as exc:
            print(f"Error: --edited-args must be valid JSON: {exc}")
            return 1
        if not isinstance(parsed, dict):
            print("Error: --edited-args must decode to a JSON object")
            return 1
        edited_arguments = parsed

    result = await loop.resume_pending_approval(
        session,
        args.approval_id,
        approved=True,
        user_feedback=args.feedback,
        edited_arguments=edited_arguments,
    )
    print(f"Approval processed. Status: {result['status']}")
    return 0


async def cmd_reject(args: argparse.Namespace, settings: AppSettings) -> int:
    """Execute the 'reject' command."""
    loop = create_agent_loop(settings)
    session = loop.repo.get_session(args.session)
    if not session:
        print(f"Error: Session {args.session} not found")
        return 1

    result = await loop.resume_pending_approval(
        session,
        args.approval_id,
        approved=False,
        user_feedback=args.feedback,
    )
    print(f"Approval processed. Status: {result['status']}")
    return 0


async def cmd_eval(args: argparse.Namespace, settings: AppSettings) -> int:
    """Execute the 'eval' command."""
    from app.evals import EvalRunner, EvalSuiteRunner, discover_fixture_paths, load_fixture

    fixture_paths = discover_fixture_paths(args.fixture)
    if len(fixture_paths) > 1 or args.fixture.resolve().is_dir():
        suite_result = await EvalSuiteRunner(settings).run_fixture_paths(fixture_paths, output_dir=args.output_dir)
        if args.json:
            print(suite_result.report_json)
        else:
            summary = suite_result.report["summary"]
            print("Eval suite run")
            print(f"Status: {suite_result.status}")
            print(f"Fixtures: {summary['fixtures_passed']}/{summary['fixtures_total']} passed")
            print(f"Average score: {suite_result.score}")
            print(f"Report: {suite_result.markdown_path}")
        return 0 if suite_result.status == "passed" else 1

    fixture = load_fixture(fixture_paths[0])
    runner = EvalRunner(settings)
    result = await runner.run_fixture(fixture, output_dir=args.output_dir)

    if args.json:
        print(result.record.report_json)
    else:
        print(f"Eval run: {result.record.id}")
        print(f"Fixture: {result.record.task_id}")
        print(f"Status: {result.record.status}")
        print(f"Score: {result.record.score}")
        print(f"Workspace: {result.workspace_path}")
        print(f"Report: {result.markdown_path}")

    return 0 if result.record.status == "passed" else 1


def _get_sync_repo(settings: AppSettings):
    """Get a synchronous repository for simple operations."""
    from app.storage.repository import SQLiteRepository

    repo = SQLiteRepository(settings.db_path)
    repo.initialize()
    return repo


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    settings = AppSettings.load()

    if args.print_layout:
        print(format_layout(settings))
        return 0

    if args.print_config:
        print(format_config(settings))
        return 0

    if not hasattr(args, "command") or args.command is None:
        parser.print_help()
        return 0

    # Run the appropriate command
    try:
        if args.command == "run":
            return asyncio.run(cmd_run(args, settings))
        elif args.command == "chat":
            return asyncio.run(cmd_chat(args, settings))
        elif args.command == "sessions":
            return asyncio.run(cmd_sessions(args, settings))
        elif args.command == "resume":
            return asyncio.run(cmd_resume(args, settings))
        elif args.command == "approvals":
            return asyncio.run(cmd_approvals(args, settings))
        elif args.command == "approve":
            return asyncio.run(cmd_approve(args, settings))
        elif args.command == "reject":
            return asyncio.run(cmd_reject(args, settings))
        elif args.command == "eval":
            return asyncio.run(cmd_eval(args, settings))
        else:
            parser.print_help()
            return 0
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
