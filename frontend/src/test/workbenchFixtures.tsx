import { render } from '@testing-library/react';
import type { FormEvent } from 'react';

import ArtifactBrowserPanel from '../components/ArtifactBrowserPanel';
import EvalDashboardPanel from '../components/EvalDashboardPanel';
import JobProgressPanel from '../components/JobProgressPanel';
import PublishingPanel from '../components/PublishingPanel';
import ResearchTrailPanel from '../components/ResearchTrailPanel';
import RichMessageContent from '../components/RichMessageContent';
import RuntimeDetailPanel from '../components/RuntimeDetailPanel';
import SessionRecoveryPanel from '../components/SessionRecoveryPanel';
import SessionSidebar from '../components/SessionSidebar';
import ToolTracePanel from '../components/ToolTracePanel';
import UsageMeterPanel from '../components/UsageMeterPanel';
import { DEFAULT_SESSION_CONTROLS, type SessionControlState } from '../sessionControls';
import type { ConnectionHealth, RecoverySnapshot } from '../workbenchState';
import type { MessagePayload, SessionDetail, SessionEventPayload, ToolCallPayload } from '../types';

function metrics() {
  return {
    session_id: 'session-1',
    turn_count: 3,
    prompt_tokens: 1200,
    completion_tokens: 800,
    total_tokens: 2000,
    estimated_cost_usd: 0.045,
    tool_calls: 8,
    tool_errors: 1,
    tool_retries: 1,
    tool_latency_ms: 90000,
    average_tool_latency_ms: 11250,
    error_count: 1,
    last_updated_at: '2026-07-01T06:10:00Z',
  };
}

function toolCall(overrides: Partial<ToolCallPayload>): ToolCallPayload {
  return {
    id: 'call-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    tool_name: 'manage_job',
    arguments: {},
    status: 'success',
    requires_approval: false,
    approval_id: null,
    started_at: '2026-07-01T06:00:00Z',
    finished_at: '2026-07-01T06:01:00Z',
    output: null,
    success: true,
    error: null,
    ...overrides,
  };
}

function message(overrides: Partial<MessagePayload>): MessagePayload {
  return {
    id: 'message-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    role: 'assistant',
    content: 'Regression fixture assistant response',
    tool_call_id: null,
    name: null,
    raw: {},
    sequence: 1,
    created_at: '2026-07-01T06:00:00Z',
    ...overrides,
  };
}

function liveEvent(overrides: Partial<SessionEventPayload>): SessionEventPayload {
  return {
    id: 'event-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    event_type: 'tool_call_started',
    data: { tool_name: 'manage_job', operation: 'run' },
    sequence: 8,
    created_at: '2026-07-01T06:01:00Z',
    ...overrides,
  };
}

export function phase5WorkbenchFixture() {
  const evalReport = {
    status: 'failed',
    summary: {
      fixtures_total: 2,
      fixtures_passed: 1,
      fixtures_failed: 1,
      fixtures_error: 0,
      average_score: 0.5,
      runtime_seconds: 9.25,
      total_tokens: 42,
    },
    fixtures: [
      {
        fixture_id: 'fixture-pass',
        status: 'passed',
        score: 1,
        markdown_path: '.ml-copilot/evals/artifacts/pass/report.md',
        report_path: '.ml-copilot/evals/artifacts/pass/report.json',
        report: {
          agent_output: { mode: 'live' },
          checks: [{ type: 'contains', passed: true, message: 'Expected text found.' }],
        },
      },
      {
        fixture_id: 'fixture-fail',
        status: 'failed',
        score: 0,
        markdown_path: '.ml-copilot/evals/artifacts/fail/report.md',
        report_path: '.ml-copilot/evals/artifacts/fail/report.json',
        report: {
          fixture: { metadata: { mode: 'scripted' } },
          scoring: { file_changes: { files_changed: ['src/train.py'] } },
          checks: [{ type: 'file_contains', passed: false, path: 'src/train.py', message: 'Metric missing.' }],
        },
      },
    ],
  };

  const toolCalls: ToolCallPayload[] = [
    toolCall({
      id: 'job-run',
      tool_name: 'manage_job',
      arguments: { operation: 'run', hardware_flavor: 'cpu-basic', timeout: '30m' },
      output: [
        '# Job launched',
        '### Job job-123',
        '- **Status:** RUNNING',
        '- **Message:** pulling image',
        '- **Hardware:** cpu-basic',
        '- **Created:** 2026-07-01T06:00:00Z',
        '- **Command:** `python train.py`',
        '- **URL:** https://huggingface.co/jobs/job-123',
      ].join('\n'),
    }),
    toolCall({
      id: 'job-logs',
      tool_name: 'manage_job',
      arguments: { operation: 'logs', job_id: 'job-123' },
      output: ['# Logs for job-123', '```', 'epoch=1 loss=0.42', 'eval accuracy=0.91', '```'].join('\n'),
    }),
    toolCall({
      id: 'sandbox-create',
      tool_name: 'experiment_workspace',
      arguments: { operation: 'create', hardware: 'cpu-basic' },
      output: [
        'Experiment workspace created.',
        '- Space: owner/ml-copilot-sandbox-session-1',
        '- URL: https://owner-ml-copilot-sandbox-session-1.hf.space',
        '- Hardware: cpu-basic',
        '- Created: 2026-07-01T06:00:00Z',
      ].join('\n'),
    }),
    toolCall({
      id: 'sandbox-run',
      tool_name: 'experiment_workspace',
      arguments: { operation: 'run', command: 'python src/train.py' },
      status: 'failed',
      success: false,
      error: 'Command failed with CUDA out of memory while training.',
    }),
    toolCall({
      id: 'publish-call',
      tool_name: 'publish_model_report',
      arguments: {
        repo_id: 'owner/model-a',
        output_dir: '.ml-copilot/reports/model-a',
        model_name: 'Model A',
        task: 'text-classification',
        datasets: ['imdb'],
        jobs: ['job-123'],
        publish: false,
      },
      output: [
        'Prepared model publishing assets.',
        '- README: .ml-copilot/reports/model-a/README.md',
        '- Final report: .ml-copilot/reports/model-a/FINAL_REPORT.md',
        '- Manifest: .ml-copilot/reports/model-a/publish_manifest.json',
        '',
        '### README.md',
        '```markdown',
        '# Model A',
        'Generated model card content.',
        '```',
        '',
        '### FINAL_REPORT.md',
        '```markdown',
        '# Final Report: Model A',
        'Recommendation: Ship after one more eval pass.',
        '```',
      ].join('\n'),
    }),
    toolCall({
      id: 'paper',
      tool_name: 'paper_details',
      arguments: { arxiv_id: '2401.12345' },
      output: [
        '# Efficient Fine-Tuning for Small Models',
        '**arxiv_id:** 2401.12345',
        'https://arxiv.org/abs/2401.12345',
        '## AI Summary',
        'Adapters improve accuracy while keeping training cost low.',
      ].join('\n'),
    }),
    toolCall({
      id: 'recipe',
      tool_name: 'extract_training_recipe',
      arguments: { arxiv_id: '2401.12345' },
      output: [
        '# Training recipe for Efficient Fine-Tuning for Small Models',
        '- evidence: "We train on IMDb and SST-2 sentiment datasets."',
        'Recipe values are extracted deterministically. Verify against read_paper before relying on them for training.',
      ].join('\n'),
    }),
    toolCall({
      id: 'eval-suite',
      tool_name: 'manage_eval_suite',
      arguments: { operation: 'run' },
      output: ['Suite report:', '```json', JSON.stringify(evalReport), '```'].join('\n'),
    }),
  ];

  const activeSession: SessionDetail = {
    id: 'session-1',
    title: 'Phase 5 regression fixture',
    status: 'running',
    model: 'zai-org/GLM-5.2:novita',
    metadata: {
      agent_controls: {
        provider: 'zai',
        reasoning_effort: 'high',
        temperature: 0.2,
        operating_mode: 'careful',
        yolo_mode: false,
        max_turns: 4,
        spend_cap_usd: 0.05,
      },
    },
    created_at: '2026-07-01T06:00:00Z',
    updated_at: '2026-07-01T06:10:00Z',
    message_count: 2,
    event_count: 12,
    pending_approval_count: 0,
    metrics: metrics(),
    pending_approvals: [],
    tool_calls: toolCalls,
  };

  const messages = [
    message({ id: 'message-user', role: 'user', content: 'Run the Phase 5 workflow.' }),
    message({ id: 'message-assistant', sequence: 2 }),
  ];

  const recoverySnapshot: RecoverySnapshot = {
    sessionId: 'session-1',
    sessionTitle: 'Phase 5 regression fixture',
    messageCount: messages.length,
    toolCallCount: toolCalls.length,
    liveEventCount: 2,
    persistedEventCount: 12,
    lastEventSequence: 9,
    replayedEventCount: 2,
    duplicateEventCount: 1,
    recoveredAt: '2026-07-01T06:10:00Z',
    status: 'recovered',
  };

  const connectionHealth: ConnectionHealth = {
    phase: 'stale',
    label: 'stream heartbeat stale',
    tone: 'warning',
    lastEventAgeMs: 125_000,
    canReconnect: true,
  };

  const draftControls: SessionControlState = {
    ...DEFAULT_SESSION_CONTROLS,
    provider: 'zai',
    reasoningEffort: 'high',
    operatingMode: 'careful',
    temperature: '0.2',
    maxTurns: '4',
    spendCapUsd: '0.05',
  };

  return {
    activeSession,
    connectionHealth,
    draftControls,
    liveEvents: [liveEvent({ id: 'event-job', sequence: 8 }), liveEvent({ id: 'event-research', sequence: 9, data: { tool_name: 'paper_details', arxiv_id: '2401.12345' } })],
    messages,
    recoverySnapshot,
    toolCalls,
  };
}

export function renderPhase5WorkbenchHarness({ onReconnect }: { onReconnect: () => void }) {
  const fixture = phase5WorkbenchFixture();
  const noop = () => undefined;
  const noopSubmit = (event: FormEvent<HTMLFormElement>) => event.preventDefault();

  return render(
    <div>
      <SessionSidebar
        activeSession={fixture.activeSession}
        creating={false}
        draftControls={fixture.draftControls}
        draftHfToken=""
        draftModel="zai-org/GLM-5.2:novita"
        draftTitle=""
        messages={fixture.messages}
        onCreateSession={noopSubmit}
        onRefreshSessions={noop}
        onSelectSession={noop}
        selectedSessionId={fixture.activeSession.id}
        sessions={[fixture.activeSession]}
        setDraftControls={noop}
        setDraftHfToken={noop}
        setDraftModel={noop}
        setDraftTitle={noop}
      />

      <RichMessageContent content={fixture.messages[1].content} />

      <SessionRecoveryPanel
        health={fixture.connectionHealth}
        snapshot={fixture.recoverySnapshot}
        onReconnect={onReconnect}
      />
      <JobProgressPanel toolCalls={fixture.toolCalls} />
      <UsageMeterPanel session={fixture.activeSession} toolCalls={fixture.toolCalls} />
      <RuntimeDetailPanel toolCalls={fixture.toolCalls} />
      <PublishingPanel toolCalls={fixture.toolCalls} />
      <ResearchTrailPanel toolCalls={fixture.toolCalls} />
      <EvalDashboardPanel toolCalls={fixture.toolCalls} />
      <ArtifactBrowserPanel toolCalls={fixture.toolCalls} />
      <ToolTracePanel
        liveEvents={fixture.liveEvents}
        metrics={fixture.activeSession.metrics}
        pendingApprovals={[]}
        toolCalls={fixture.toolCalls}
      />
    </div>,
  );
}
