// PandaChip run API — wraps the Go server (web/) endpoints.

import { getApiBaseUrl } from '@/api/auth'

export type RunState = 'running' | 'paused' | 'completed' | 'needs_review' | 'failed'

// A phase is 'done' only when the agent's tool layer witnessed the artifact
// that defines it; 'incomplete' means the run ended while it was skipped.
export type PhaseStatus = 'pending' | 'running' | 'done' | 'incomplete'

export interface RunSummary {
  run_id: string
  state: RunState
  prompt: string
  created: string
  model?: string
  pdk?: string
}

export interface RunOutcome {
  status: string
  steps?: number
  summary?: string
  evidence?: string
  spec_met?: boolean
  last_text?: string
  wall_seconds?: number
  phases_incomplete?: string[]
}

export interface RunDetail {
  run_id: string
  state: RunState
  prompt: string
  created: string
  model?: string
  pdk?: string
  outcome: RunOutcome | null
  phases: { phase: string; status: PhaseStatus; at?: string; note?: string }[] | null
  plots: string[] | null
  artifacts: string[] | null
  log_tail: string
  report?: boolean
}

async function parseError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { error?: string }
    return payload.error ?? `${response.status} ${response.statusText}`
  } catch {
    return `${response.status} ${response.statusText}`
  }
}

export async function listRuns(): Promise<RunSummary[]> {
  const response = await fetch(`${getApiBaseUrl()}/api/runs`)
  if (!response.ok) {
    throw new Error(await parseError(response))
  }
  return (await response.json()) as RunSummary[]
}

export async function getRun(runId: string): Promise<RunDetail> {
  const response = await fetch(`${getApiBaseUrl()}/api/run/${encodeURIComponent(runId)}`)
  if (!response.ok) {
    throw new Error(await parseError(response))
  }
  return (await response.json()) as RunDetail
}

export interface StartRunOptions {
  name?: string
  model?: string
  pdk?: string
  files?: File[]
}

export async function startRun(prompt: string, options: StartRunOptions = {}): Promise<{ run_id: string }> {
  const form = new FormData()
  form.set('prompt', prompt)
  if (options.name) form.set('name', options.name)
  if (options.model) form.set('model', options.model)
  if (options.pdk) form.set('pdk', options.pdk)
  for (const file of options.files ?? []) {
    form.append('files', file, file.name)
  }
  const response = await fetch(`${getApiBaseUrl()}/api/run`, {
    method: 'POST',
    body: form,
  })
  if (!response.ok) {
    throw new Error(await parseError(response))
  }
  return (await response.json()) as { run_id: string }
}

export async function listModels(): Promise<{ models: string[]; default: string }> {
  const response = await fetch(`${getApiBaseUrl()}/api/models`)
  if (!response.ok) {
    throw new Error(await parseError(response))
  }
  return (await response.json()) as { models: string[]; default: string }
}

export async function listPdks(): Promise<{ pdks: string[]; default: string; note?: string }> {
  const response = await fetch(`${getApiBaseUrl()}/api/pdks`)
  if (!response.ok) {
    throw new Error(await parseError(response))
  }
  return (await response.json()) as { pdks: string[]; default: string; note?: string }
}

export async function openInXschem(runId: string, file?: string): Promise<{ opened: string }> {
  const response = await fetch(`${getApiBaseUrl()}/api/xschem/${encodeURIComponent(runId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(file ? { file } : {}),
  })
  if (!response.ok) {
    throw new Error(await parseError(response))
  }
  return (await response.json()) as { opened: string }
}

export interface Suggestion {
  title: string
  detail: string
}

export async function getSuggestions(runId: string): Promise<{ model: string; suggestions: Suggestion[] }> {
  const response = await fetch(`${getApiBaseUrl()}/api/suggest/${encodeURIComponent(runId)}`)
  if (!response.ok) {
    throw new Error(await parseError(response))
  }
  return (await response.json()) as { model: string; suggestions: Suggestion[] }
}

export async function resumeRun(runId: string): Promise<void> {
  const response = await fetch(`${getApiBaseUrl()}/api/resume/${encodeURIComponent(runId)}`, {
    method: 'POST',
  })
  if (!response.ok) {
    throw new Error(await parseError(response))
  }
}

// Toggles: pauses a running agent (SIGSTOP), continues a paused one
// (SIGCONT). Returns the new state.
export async function pauseRun(runId: string): Promise<'paused' | 'running'> {
  const response = await fetch(`${getApiBaseUrl()}/api/pause/${encodeURIComponent(runId)}`, {
    method: 'POST',
  })
  if (!response.ok) {
    throw new Error(await parseError(response))
  }
  const payload = (await response.json()) as { state: 'paused' | 'running' }
  return payload.state
}

export async function deleteRun(runId: string): Promise<void> {
  const response = await fetch(`${getApiBaseUrl()}/api/run/${encodeURIComponent(runId)}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error(await parseError(response))
  }
}

export function artifactUrl(runId: string, path: string) {
  return `${getApiBaseUrl()}/api/artifact/${encodeURIComponent(runId)}/${path}`
}
