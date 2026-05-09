"""Bootstrap entrypoint for the ML Copilot application."""

from __future__ import annotations

import argparse
import asyncio
import logging

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
    sessions_parser = subparsers.add_parser("sessions", help="List all sessions")

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
    repo = asyncio.run(  # noqa: PTH003 - Using sync repo for simplicity
        asyncio.to_thread(lambda: _get_sync_repo(settings))
    )
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
