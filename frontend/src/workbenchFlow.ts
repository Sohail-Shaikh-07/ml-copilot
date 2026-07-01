import type { MessagePayload, SessionDetail, ToolCallPayload } from './types';
import type { RecoverySnapshot } from './workbenchState';

export type WorkbenchStageId = 'setup' | 'data' | 'research' | 'runtime' | 'monitor' | 'artifacts' | 'evals' | 'publish';
export type WorkbenchStageStatus = 'complete' | 'active' | 'waiting';

export interface WorkbenchStage {
  id: WorkbenchStageId;
  title: string;
  summary: string;
  status: WorkbenchStageStatus;
  href: string;
  evidence: string[];
}

export interface WorkbenchFlowSummary {
  completedCount: number;
  totalCount: number;
  resumeLabel: string;
  stages: WorkbenchStage[];
  walkthrough: string[];
}

interface WorkbenchFlowInput {
  session: SessionDetail | null;
  messages: MessagePayload[];
  toolCalls: ToolCallPayload[];
  recovery: RecoverySnapshot | null;
}

function textForCall(call: ToolCallPayload) {
  return `${call.tool_name} ${JSON.stringify(call.arguments)} ${call.output ?? ''} ${call.error ?? ''}`.toLowerCase();
}

function hasTool(toolCalls: ToolCallPayload[], names: string[]) {
  return toolCalls.some((call) => names.includes(call.tool_name));
}

function evidenceFor(toolCalls: ToolCallPayload[], predicate: (call: ToolCallPayload) => boolean, fallback: string) {
  const match = toolCalls.find(predicate);
  if (!match) return [];
  return [match.tool_name, match.id || fallback].filter(Boolean);
}

function statusFor(completed: boolean, priorComplete: boolean): WorkbenchStageStatus {
  if (completed) return 'complete';
  return priorComplete ? 'active' : 'waiting';
}

export function buildWorkbenchFlowSummary({ session, messages, toolCalls, recovery }: WorkbenchFlowInput): WorkbenchFlowSummary {
  const setupComplete = Boolean(session?.model || session?.metadata.agent_controls);
  const dataComplete = toolCalls.some((call) => {
    const text = textForCall(call);
    return ['inspect_dataset', 'hf_inspect_dataset'].includes(call.tool_name)
      || text.includes('dataset')
      || text.includes('.csv')
      || text.includes('data/');
  });
  const researchComplete = hasTool(toolCalls, [
    'paper_details',
    'paper_citation_graph',
    'read_paper',
    'extract_training_recipe',
    'hf_papers',
    'search_hub',
    'hf_search_hub',
  ]);
  const runtimeComplete = hasTool(toolCalls, ['experiment_workspace', 'manage_job']);
  const monitorComplete = Boolean(recovery || toolCalls.length > 0);
  const artifactsComplete = toolCalls.some((call) => {
    const text = textForCall(call);
    return text.includes('readme.md')
      || text.includes('final_report.md')
      || text.includes('manifest')
      || text.includes('wrote ')
      || text.includes('.ml-copilot/');
  });
  const evalsComplete = hasTool(toolCalls, ['manage_eval_suite']);
  const publishComplete = hasTool(toolCalls, ['publish_model_report']);

  const definitions = [
    {
      id: 'setup' as const,
      title: 'Choose model and operating mode',
      summary: session?.model ? `Session is configured for ${session.model}.` : 'Pick provider, model, effort, and safety preferences.',
      href: '#model-provider-controls',
      completed: setupComplete,
      evidence: session?.model ? [session.model] : [],
    },
    {
      id: 'data' as const,
      title: 'Ingest or inspect data',
      summary: 'Bring datasets, previews, and generated files into the workbench context.',
      href: '#artifact-browser',
      completed: dataComplete,
      evidence: evidenceFor(toolCalls, (call) => textForCall(call).includes('dataset'), 'dataset'),
    },
    {
      id: 'research' as const,
      title: 'Research papers, recipes, and Hub candidates',
      summary: 'Connect papers, recipes, datasets, and models to decisions.',
      href: '#research-trail',
      completed: researchComplete,
      evidence: evidenceFor(toolCalls, (call) => ['paper_details', 'extract_training_recipe', 'search_hub'].includes(call.tool_name), 'research'),
    },
    {
      id: 'runtime' as const,
      title: 'Run sandbox or hosted jobs',
      summary: 'Launch code, monitor jobs, and inspect runtime logs.',
      href: '#runtime-details',
      completed: runtimeComplete,
      evidence: evidenceFor(toolCalls, (call) => ['experiment_workspace', 'manage_job'].includes(call.tool_name), 'runtime'),
    },
    {
      id: 'monitor' as const,
      title: 'Monitor usage, traces, and recovery',
      summary: recovery ? `Recovered ${recovery.toolCallCount} tool calls and ${recovery.messageCount} messages.` : 'Watch tool traces, cost estimates, and session recovery state.',
      href: '#tool-trace',
      completed: monitorComplete,
      evidence: recovery ? [`event #${recovery.lastEventSequence}`] : [],
    },
    {
      id: 'artifacts' as const,
      title: 'Inspect files and artifacts',
      summary: 'Open generated datasets, reports, manifests, and sandbox outputs.',
      href: '#artifact-browser',
      completed: artifactsComplete,
      evidence: evidenceFor(toolCalls, (call) => textForCall(call).includes('readme.md') || textForCall(call).includes('wrote '), 'artifact'),
    },
    {
      id: 'evals' as const,
      title: 'Run evals and check release gates',
      summary: 'Review fixture results, failures, changed files, and gate status.',
      href: '#eval-dashboard',
      completed: evalsComplete,
      evidence: evidenceFor(toolCalls, (call) => call.tool_name === 'manage_eval_suite', 'eval'),
    },
    {
      id: 'publish' as const,
      title: 'Generate final report and publish intentionally',
      summary: 'Preview model cards, final reports, manifests, provenance, and publish state.',
      href: '#publishing-panel',
      completed: publishComplete,
      evidence: evidenceFor(toolCalls, (call) => call.tool_name === 'publish_model_report', 'publish'),
    },
  ];

  let priorComplete = true;
  const stages = definitions.map((definition) => {
    const status = statusFor(definition.completed, priorComplete);
    priorComplete = priorComplete && definition.completed;
    return { ...definition, status };
  });

  return {
    completedCount: stages.filter((stage) => stage.status === 'complete').length,
    totalCount: stages.length,
    resumeLabel: recovery ? `Recovered through event #${recovery.lastEventSequence}` : 'No recovery snapshot yet',
    stages,
    walkthrough: [
      'Choose provider, model, effort, and safety controls before starting the run.',
      'Attach or inspect data so the agent has concrete inputs.',
      'Research papers, training recipes, datasets, and model candidates.',
      'Launch sandbox commands or hosted jobs and monitor runtime state.',
      'Use traces, usage estimates, and recovery state to understand progress after refresh.',
      'Inspect generated files, reports, manifests, and sandbox outputs.',
      'Run evals and resolve release-gate failures before publishing.',
      'Generate the final report and publish only after reviewing provenance and token state.',
    ],
  };
}
