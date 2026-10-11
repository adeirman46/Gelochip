import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  Activity,
  AppWindow,
  CheckCircle2,
  CircleDashed,
  Clock,
  FileDown,
  FileText,
  Lightbulb,
  Loader2,
  Pause,
  Play,
  RotateCcw,
  ScrollText,
  Waves,
} from 'lucide-react'

import { getApiBaseUrl } from '@/api/auth'
import { artifactUrl, getRun, getSuggestions, openInXschem, pauseRun, resumeRun, type RunDetail, type Suggestion } from '@/api/runs'
import { ErrorState, LoadingState, SummaryRow } from '@/components/app/shared'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useToast } from '@/hooks/use-toast'

const stateBadge: Record<string, string> = {
  completed: 'bg-emerald-100 text-emerald-700',
  running: 'bg-sky-100 text-sky-700',
  paused: 'bg-violet-100 text-violet-700',
  needs_review: 'bg-amber-100 text-amber-700',
  failed: 'bg-rose-100 text-rose-700',
}

const PHASES = [
  { key: 'spec_ingestion', label: 'Spec Ingestion' },
  { key: 'plan', label: 'Plan' },
  { key: 'sch_gen', label: 'Sch Gen' },
  { key: 'tb_gen', label: 'TB Gen' },
  { key: 'sim', label: 'Sim' },
]

const PHASE_LABEL: Record<string, string> = Object.fromEntries(PHASES.map((p) => [p.key, p.label]))

type Tab = 'runbook' | 'workspace' | 'simulation'

interface LogEvent {
  step: string
  title: string
  detail: string
  result?: string
  tone?: Tone
  agent?: string
}

function pick(source: string, key: string): string | null {
  const m = source.match(new RegExp('"' + key + '":\\s*"((?:[^"\\\\]|\\\\.)*)"'))
  // The log holds JSON-encoded arguments: unescape so a quoted search
  // phrase reads as "Dickson Charge Pump", never \"Dickson Charge Pump\".
  return m ? m[1].replace(/\\"/g, '"').replace(/\\n/g, ' ').replace(/\\\\/g, '\\') : null
}

const PHASE_TITLE: Record<string, string> = {
  spec_ingestion: 'Spec ingestion',
  plan: 'Planning',
  sch_gen: 'Schematic generation',
  tb_gen: 'Testbench generation',
  sim: 'Simulation',
}

// A URL is unreadable at full length in a log row; the host plus the
// last meaningful path segment is what identifies the source.
function shortUrl(url: string): string {
  try {
    const u = new URL(url)
    const host = u.hostname.replace(/^www\./, '')
    const tail = u.pathname.split('/').filter(Boolean).pop()
    return tail ? `${host}/${tail.length > 44 ? tail.slice(0, 44) + '…' : tail}` : host
  } catch {
    return url.length > 60 ? url.slice(0, 60) + '…' : url
  }
}

// Last resort: turn a raw JSON argument blob into "key: value" prose
// rather than showing the user braces and quotes. Log lines are clipped
// mid-JSON, so an unterminated trailing value still has to render.
function humanizeArgs(args: string): string {
  const pairs = [...args.matchAll(/"(\w+)":\s*"((?:[^"\\]|\\.){0,120})"/g)]
    .map(([, k, v]) => `${k.replace(/_/g, ' ')}: ${v}`)
  if (pairs.length > 0) return pairs.join(' · ')
  const truncated = args.match(/"(\w+)":\s*"((?:[^"\\]|\\.)+)$/)
  if (truncated) return `${truncated[1].replace(/_/g, ' ')}: ${truncated[2]}…`
  const bare = args.match(/"(\w+)":\s*([\d.eE+-]+|true|false)/)
  return bare ? `${bare[1].replace(/_/g, ' ')}: ${bare[2]}` : 'running…'
}

function describeCall(tool: string, args: string): string {
  switch (tool) {
    case 'write_file':
      return `Wrote ${pick(args, 'path') ?? 'a file'}`
    case 'read_file':
      return `Read ${pick(args, 'path') ?? 'a file'}`
    case 'netlist_schematic':
      return `Netlisted ${pick(args, 'schematic') ?? 'a schematic'} with xschem`
    case 'simulate_netlist':
      return `Simulated ${pick(args, 'netlist') ?? 'a netlist'} with ngspice`
    case 'analyze_raw': {
      const vectors = [...args.matchAll(/"((?:v\([^)]*\)|[a-z0-9_.]+))"/gi)]
        .map((m) => m[1])
        .filter((v) => v !== pick(args, 'raw_path'))
      const where = pick(args, 'raw_path') ?? 'a rawfile'
      return vectors.length > 0
        ? `Measured ${vectors.slice(0, 6).join(', ')}${vectors.length > 6 ? ` +${vectors.length - 6} more` : ''} in ${where}`
        : `Measured waveforms in ${where}`
    }
    case 'plot_xy':
      return `Charted ${pick(args, 'title') ?? pick(args, 'name') ?? 'a sweep'}`
    case 'search_web':
      return `Searched for “${pick(args, 'query') ?? '…'}”`
    case 'fetch_reference': {
      const url = pick(args, 'url')
      return url ? `Fetched ${shortUrl(url)}` : 'Fetched a reference'
    }
    case 'set_phase': {
      const phase = pick(args, 'phase') ?? ''
      return `Started ${PHASE_TITLE[phase] ?? phase}`
    }
    case 'done':
      return /"spec_met":\s*true/.test(args) ? 'Declared the spec met' : 'Finished, spec not fully met'
    case 'task': {
      const who = pick(args, 'subagent_type') ?? pick(args, 'name')
      // The log line is clipped, so the description often has no closing
      // quote: fall back to whatever text follows the key.
      const raw =
        pick(args, 'description') ??
        args.match(/"description":\s*"((?:[^"\\]|\\.)+)$/)?.[1]?.replace(/\\n/g, ' ').replace(/\\"/g, '"') ??
        ''
      const what = raw.trim().slice(0, 160)
      const label = who ? `Dispatched ${who}` : 'Dispatched a subagent'
      return what ? `${label} — ${what}${raw.length > 160 ? '…' : ''}` : label
    }
    case 'write_todos': {
      // Show the list as a checklist, not as JSON objects.
      const items = [...args.matchAll(/"status":\s*"(\w+)"[^}]*?"content":\s*"((?:[^"\\]|\\.)+?)"/g)]
        .map(([, status, content]) => `${status === 'completed' ? '✓' : status === 'in_progress' ? '▸' : '○'} ${content}`)
      return items.length > 0 ? `Task list — ${items.join('  ')}` : 'Updated the task list'
    }
    case 'workflow_status':
      return 'Checked what still stands between this run and done'
    default:
      return humanizeArgs(args)
  }
}

function describeResult(tool: string, result: string): string {
  const summary = pick(result, 'summary')
  const bytes = result.match(/"bytes":\s*(\d+)/)
  const eng = pick(result, 'engineering')
  const err = pick(result, 'error') || pick(result, 'message')
  if (tool === 'write_file' && bytes) return `Saved, ${Number(bytes[1]).toLocaleString()} bytes`
  if (summary) return `${eng === 'pass' ? 'Passed — ' : eng === 'unknown' ? 'Needs attention — ' : ''}${summary}`
  if (err) return err.replace(/^fetch failed:\s*/, '').slice(0, 180)
  if (tool === 'set_phase') {
    const missing = result.match(/"phases_without_evidence":\s*\[([^\]]*)\]/)
    const list = missing ? [...missing[1].matchAll(/"(\w+)"/g)].map((m) => PHASE_TITLE[m[1]] ?? m[1]) : []
    return list.length > 0 ? `Announced — still awaiting evidence: ${list.join(', ')}` : 'Announced, evidence complete'
  }
  if (tool === 'search_web' || tool === 'fetch_reference') return 'Saved to the reference library'
  if (/"ok":\s*true/.test(result)) return 'Done'
  return humanizeArgs(result)
}

// Lines are "[12] tool: ..." from the orchestrator, or
// "[12] <block-designer> tool: ..." from a subagent working in its own
// context. The agent name is captured so the UI can attribute each step.
function parseEvents(log: string): LogEvent[] {
  const events: LogEvent[] = []
  for (const line of (log || '').split('\n')) {
    let m = line.match(/^\[(\d+)\](?: <([\w-]+)>)? tool: (\w+)\((.*)$/)
    if (m) {
      events.push({ step: m[1], agent: m[2], title: m[3], detail: describeCall(m[3], m[4]) })
      continue
    }
    m = line.match(/^\[(\d+)\](?: <[\w-]+>)?\s+-> (.*)$/)
    if (m && events.length > 0) {
      const last = events[events.length - 1]
      last.result = describeResult(last.title, m[2])
      last.tone = resultTone(m[2])
      continue
    }
    m = line.match(/^\[(\d+)\](?: <([\w-]+)>)? assistant: (.*)$/)
    if (m) {
      events.push({ step: m[1], agent: m[2], title: 'assistant', detail: m[3].slice(0, 300) })
    }
  }
  return events.slice(-40)
}

// One accent per kind of work, so the log reads as coloured bands at a
// glance: research is indigo, drawing is sky/violet, running is amber,
// evidence is emerald. Tailwind needs literal class names, not built ones.
const TOOL_META: Record<string, { label: string; pill: string; bar: string }> = {
  write_file: { label: 'Write', pill: 'bg-sky-50 text-sky-700 ring-sky-200', bar: 'bg-sky-400' },
  read_file: { label: 'Read', pill: 'bg-cyan-50 text-cyan-700 ring-cyan-200', bar: 'bg-cyan-400' },
  netlist_schematic: { label: 'Netlist', pill: 'bg-violet-50 text-violet-700 ring-violet-200', bar: 'bg-violet-400' },
  simulate_netlist: { label: 'Simulate', pill: 'bg-amber-50 text-amber-700 ring-amber-200', bar: 'bg-amber-400' },
  analyze_raw: { label: 'Measure', pill: 'bg-emerald-50 text-emerald-700 ring-emerald-200', bar: 'bg-emerald-400' },
  plot_xy: { label: 'Chart', pill: 'bg-fuchsia-50 text-fuchsia-700 ring-fuchsia-200', bar: 'bg-fuchsia-400' },
  search_web: { label: 'Research', pill: 'bg-indigo-50 text-indigo-700 ring-indigo-200', bar: 'bg-indigo-400' },
  fetch_reference: { label: 'Reference', pill: 'bg-indigo-50 text-indigo-700 ring-indigo-200', bar: 'bg-indigo-400' },
  set_phase: { label: 'Phase', pill: 'bg-lime-50 text-lime-700 ring-lime-200', bar: 'bg-lime-400' },
  done: { label: 'Finish', pill: 'bg-emerald-50 text-emerald-700 ring-emerald-200', bar: 'bg-emerald-500' },
  assistant: { label: 'Thinking', pill: 'bg-stone-100 text-stone-600 ring-stone-200', bar: 'bg-stone-300' },
  // Deep-agent orchestration: dispatching a subagent and revising the
  // task list are the headline events, so they get the strongest accent.
  task: { label: 'Subagent', pill: 'bg-rose-50 text-rose-700 ring-rose-200', bar: 'bg-rose-400' },
  write_todos: { label: 'Task list', pill: 'bg-teal-50 text-teal-700 ring-teal-200', bar: 'bg-teal-400' },
  workflow_status: { label: 'Check', pill: 'bg-slate-100 text-slate-700 ring-slate-300', bar: 'bg-slate-400' },
}

const FALLBACK_META = { label: 'Step', pill: 'bg-stone-100 text-stone-600 ring-stone-200', bar: 'bg-stone-300' }

type Tone = 'ok' | 'error' | 'neutral'

// Tone is decided from the RAW tool result, before it is prettified —
// the prettified text no longer carries the JSON status fields.
function resultTone(raw: string): Tone {
  if (/"error"|invalid|nonzero_exit|not_fresh|rejected|failed|Forbidden|"engineering": "unknown"/.test(raw)) return 'error'
  if (/"ok":\s*true|"engineering": "pass"|"execution": "completed"/.test(raw)) return 'ok'
  return 'neutral'
}

const TONE_TEXT: Record<Tone, string> = {
  ok: 'text-emerald-600',
  error: 'text-rose-600',
  neutral: 'text-stone-500',
}

function PhaseTimeline({ run, reportBusy, reportError, onExport }: { run: RunDetail; reportBusy: boolean; reportError: boolean; onExport: () => void }) {
  // Each phase reports its OWN status from the server ledger. A phase is
  // green only when the tool layer witnessed its artifact, so a skipped
  // phase stays visibly unfinished even on a run the agent called done.
  const ledger = new Map((run.phases ?? []).map((p) => [p.phase, p]))
  const finished = run.state === 'completed' || run.state === 'needs_review'
  const skipped = PHASES.filter((p) => (ledger.get(p.key)?.status ?? 'pending') !== 'done')
  return (
    <Card className='rounded-3xl border-stone-200'>
      <CardHeader className='pb-2'>
        <CardTitle className='flex items-center justify-between text-base'>
          Phase timeline
          <Badge className='rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700'>Live</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className='grid grid-cols-2 gap-2 sm:grid-cols-6'>
          {PHASES.map((phase) => {
            const entry = ledger.get(phase.key)
            const status = entry?.status ?? 'pending'
            const bar =
              status === 'done'
                ? 'bg-emerald-500'
                : status === 'running'
                  ? 'bg-sky-500 animate-pulse'
                  : status === 'incomplete'
                    ? 'bg-amber-500'
                    : 'bg-stone-200'
            const title =
              status === 'done'
                ? entry?.note ?? 'Evidence recorded'
                : status === 'running'
                  ? 'In progress — no artifact yet'
                  : status === 'incomplete'
                    ? 'Skipped: the run ended without this phase producing its artifact'
                    : 'Not started'
            return (
              <div key={phase.key} className='rounded-2xl border border-stone-200 p-3' title={title}>
                <div className='flex items-center justify-between gap-1'>
                  <p className='truncate text-xs font-semibold uppercase tracking-wide text-stone-700'>{phase.label}</p>
                  {status === 'done' ? (
                    <CheckCircle2 className='h-4 w-4 shrink-0 text-emerald-500' />
                  ) : status === 'running' ? (
                    <Loader2 className='h-4 w-4 shrink-0 animate-spin text-sky-500' />
                  ) : status === 'incomplete' ? (
                    <Clock className='h-4 w-4 shrink-0 text-amber-500' />
                  ) : (
                    <CircleDashed className='h-4 w-4 shrink-0 text-stone-300' />
                  )}
                </div>
                <div className={`mt-2 h-1.5 rounded-full ${bar}`} />
              </div>
            )
          })}
          {(() => {
            // Match the other tiles: green = report ready, blue = building,
            // red ONLY on failure, neutral = idle/not-yet-built.
            const rState = reportError ? 'attention' : reportBusy ? 'running' : run.report ? 'done' : 'pending'
            const rText =
              rState === 'attention' ? 'text-rose-700' : rState === 'done' ? 'text-stone-700' : 'text-stone-700'
            const rBar =
              rState === 'done'
                ? 'bg-emerald-500'
                : rState === 'running'
                  ? 'bg-sky-500 animate-pulse'
                  : rState === 'attention'
                    ? 'bg-rose-500'
                    : 'bg-stone-200'
            return (
              <button
                type='button'
                disabled={!finished || reportBusy}
                onClick={onExport}
                title={run.report ? 'View the PDF report' : finished ? 'Generate the IEEE-style PDF report' : 'Available once the run finishes'}
                className={`rounded-2xl border border-stone-200 p-3 text-left transition ${finished ? 'hover:border-emerald-300' : 'opacity-50'}`}
              >
                <div className='flex items-center justify-between gap-1'>
                  <p className={`truncate text-xs font-semibold uppercase tracking-wide ${rText}`}>Report</p>
                  {rState === 'done' ? (
                    <CheckCircle2 className='h-4 w-4 shrink-0 text-emerald-500' />
                  ) : rState === 'running' ? (
                    <Loader2 className='h-4 w-4 shrink-0 animate-spin text-sky-500' />
                  ) : rState === 'attention' ? (
                    <Clock className='h-4 w-4 shrink-0 text-rose-500' />
                  ) : (
                    <FileDown className='h-4 w-4 shrink-0 text-stone-400' />
                  )}
                </div>
                <div className={`mt-2 h-1.5 rounded-full ${rBar}`} />
              </button>
            )
          })()}
        </div>
        {finished && skipped.length > 0 && (
          <p className='mt-3 rounded-2xl bg-amber-50 px-3 py-2 text-xs text-amber-800'>
            Workflow incomplete — {skipped.map((p) => PHASE_LABEL[p.key]).join(', ')}{' '}
            {skipped.length === 1 ? 'never produced its artifact' : 'never produced their artifacts'}. The
            agent skipped {skipped.length === 1 ? 'this step' : 'these steps'}, so this run is not a clean
            pass whatever its summary claims.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export function RunDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { toast } = useToast()
  const [run, setRun] = useState<RunDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('runbook')
  const [selected, setSelected] = useState<string | null>(null)
  const [fileText, setFileText] = useState<string>('')
  const [suggestions, setSuggestions] = useState<Suggestion[] | null>(null)
  const [suggestLoading, setSuggestLoading] = useState(false)
  const [reportBusy, setReportBusy] = useState(false)
  const [reportError, setReportError] = useState(false)

  useEffect(() => {
    if (!selected || !id || /\.(png|jpe?g|webp|gif|pdf|raw)$/i.test(selected)) {
      setFileText('')
      return
    }
    void (async () => {
      try {
        const res = await fetch(artifactUrl(id, selected))
        setFileText((await res.text()).slice(0, 40000))
      } catch {
        setFileText('(could not load file)')
      }
    })()
  }, [selected, id])

  const refresh = useCallback(async () => {
    if (!id) {
      return
    }
    try {
      setRun(await getRun(id))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load the run')
    }
  }, [id])

  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), 4000)
    return () => clearInterval(timer)
  }, [refresh])

  useEffect(() => {
    if (!id || !run || suggestions !== null || suggestLoading) {
      return
    }
    if (run.state !== 'needs_review' && run.state !== 'failed') {
      return
    }
    setSuggestLoading(true)
    getSuggestions(id)
      .then((data) => setSuggestions(data.suggestions))
      .catch(() => setSuggestions([]))
      .finally(() => setSuggestLoading(false))
  }, [id, run, suggestions, suggestLoading])

  async function handleRetry() {
    if (!id) {
      return
    }
    try {
      await resumeRun(id)
      toast({ title: 'Run retrying', description: 'The agent picked the task back up.' })
      setSuggestions(null)
      void refresh()
    } catch (err) {
      toast({
        title: 'Could not retry',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    }
  }

  async function handlePause() {
    if (!id) {
      return
    }
    try {
      const state = await pauseRun(id)
      toast({
        title: state === 'paused' ? 'Run paused' : 'Run continued',
        description:
          state === 'paused'
            ? 'The agent process is frozen; press Continue to let it carry on.'
            : 'The agent picked up right where it stopped.',
      })
      void refresh()
    } catch (err) {
      toast({
        title: 'Could not pause',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    }
  }

  async function handleExportReport() {
    if (!id || reportBusy) {
      return
    }
    setReportBusy(true)
    setReportError(false)
    toast({ title: 'Building PDF report', description: 'Rendering schematics and compiling LaTeX — this can take a minute.' })
    try {
      // First request generates + caches the PDF server-side (may take ~1 min).
      const res = await fetch(`${getApiBaseUrl()}/api/report/${encodeURIComponent(id)}`)
      if (!res.ok) {
        const msg = await res.json().catch(() => ({ error: 'failed' }))
        throw new Error(msg.error ?? 'report failed')
      }
      // Open the served URL directly — the browser's native PDF viewer
      // renders it (blob: URLs often show blank in a new tab).
      window.open(`${getApiBaseUrl()}/api/report/${encodeURIComponent(id)}`, '_blank')
      toast({ title: 'PDF report ready', description: 'Opened in a new tab.' })
      void refresh()
    } catch (err) {
      setReportError(true)
      toast({
        title: 'Could not build report',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    } finally {
      setReportBusy(false)
    }
  }

  async function handleOpenXschem() {
    if (!id) {
      return
    }
    try {
      const { opened } = await openInXschem(id)
      toast({ title: 'xschem GUI launched', description: `${opened} opened on the workstation display.` })
    } catch (err) {
      toast({
        title: 'Could not open xschem',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    }
  }

  if (error) {
    return <ErrorState title='Could not load the run' detail={error} onRetry={() => void refresh()} />
  }

  if (!run) {
    return <LoadingState label='Loading run…' />
  }

  const schematics = (run.artifacts ?? []).filter((a) => a.endsWith('.sch'))
  // Chip-Orchestra-style grouping: the important design files first, then
  // supporting material, so the browser reads like a project tree.
  const fileCategory = (p: string): string => {
    if (p.startsWith('exp/')) return 'Experiments & versions'
    if (p.startsWith('context/')) return 'Research references'
    if (p.startsWith('uploads/')) return 'Uploads'
    if (p.startsWith('sim/')) return 'Simulation logs'
    if (/\.(sch|sym)$/.test(p)) return 'Design — schematics & symbols'
    if (/\.(spice|cir)$/.test(p)) return 'Netlists & decks'
    if (/\.raw$/.test(p)) return 'Rawfiles'
    if (/\.(png|jpe?g|webp|gif)$/i.test(p)) return 'Plots & images'
    if (/\.md$/.test(p)) return 'Docs & plans'
    return 'Other'
  }
  const categoryOrder = [
    'Design — schematics & symbols',
    'Netlists & decks',
    'Plots & images',
    'Experiments & versions',
    'Rawfiles',
    'Simulation logs',
    'Docs & plans',
    'Research references',
    'Uploads',
    'Other',
  ]
  const groupedFiles = categoryOrder
    .map((cat) => [cat, (run.artifacts ?? []).filter((a) => fileCategory(a) === cat)] as const)
    .filter(([, files]) => files.length > 0)

  return (
    <div className='space-y-4'>
      <div className='flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between'>
        <div className='flex flex-wrap items-center gap-3'>
          <h2 className='text-2xl font-semibold text-stone-900'>{run.run_id}</h2>
          <Badge className={`rounded-full px-3 py-1 ${stateBadge[run.state] ?? stateBadge.needs_review}`}>
            {run.state.replace('_', ' ')}
          </Badge>
          {run.model ? <Badge className='rounded-full bg-stone-100 px-3 py-1 text-stone-600'>{run.model}</Badge> : null}
          {run.pdk ? <Badge className='rounded-full bg-lime-100 px-3 py-1 text-lime-700'>{run.pdk}</Badge> : null}
        </div>
        <div className='flex items-center gap-2'>
          {run.state === 'running' || run.state === 'paused' ? (
            <Button
              variant='outline'
              className={`rounded-2xl border-stone-200 ${run.state === 'paused' ? 'text-emerald-600' : 'text-amber-600'}`}
              onClick={() => void handlePause()}
            >
              {run.state === 'paused' ? <Play className='mr-2 h-4 w-4' /> : <Pause className='mr-2 h-4 w-4' />}
              {run.state === 'paused' ? 'Continue' : 'Pause'}
            </Button>
          ) : null}
          {run.state !== 'running' && run.state !== 'paused' && run.state !== 'completed' ? (
            <Button
              variant='outline'
              className='rounded-2xl border-stone-200 text-sky-600'
              onClick={() => void handleRetry()}
            >
              <RotateCcw className='mr-2 h-4 w-4' />
              Retry
            </Button>
          ) : null}
          <Button
            variant='outline'
            className={`rounded-2xl border-stone-200 ${reportError ? 'text-rose-600' : run.report ? 'text-emerald-600' : 'text-stone-700'}`}
            disabled={reportBusy}
            onClick={() => void handleExportReport()}
          >
            {reportBusy ? <Loader2 className='mr-2 h-4 w-4 animate-spin' /> : <FileDown className='mr-2 h-4 w-4' />}
            {reportBusy ? 'Building PDF…' : run.report ? 'View PDF report' : 'Export PDF report'}
          </Button>
          <Button onClick={handleOpenXschem} className='rounded-2xl bg-emerald-600 hover:bg-emerald-700' disabled={schematics.length === 0}>
            <AppWindow className='mr-2 h-4 w-4' />
            Open in xschem GUI
          </Button>
        </div>
      </div>

      <PhaseTimeline run={run} reportBusy={reportBusy} reportError={reportError} onExport={() => void handleExportReport()} />

      {run.state === 'needs_review' || run.state === 'failed' ? (
        <Card className='rounded-3xl border-amber-200 bg-amber-50/60'>
          <CardHeader className='pb-2'>
            <CardTitle className='flex items-center gap-2 text-amber-800'>
              <Lightbulb className='h-5 w-5' />
              Needs review — AI suggestions
            </CardTitle>
          </CardHeader>
          <CardContent className='space-y-3'>
            {suggestLoading ? (
              <p className='flex items-center gap-2 text-sm text-amber-700'>
                <Loader2 className='h-4 w-4 animate-spin' />
                The run&apos;s model is reviewing the outcome and transcript…
              </p>
            ) : suggestions && suggestions.length > 0 ? (
              <ul className='space-y-2'>
                {suggestions.map((s, i) => (
                  <li key={i} className='rounded-2xl bg-white/80 p-3 text-sm'>
                    <p className='font-semibold text-stone-800'>{s.title}</p>
                    <p className='mt-0.5 text-stone-600'>{s.detail}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className='text-sm text-amber-700'>No suggestions available — check the run log below.</p>
            )}
            <Button onClick={() => void handleRetry()} className='rounded-2xl bg-amber-600 text-white hover:bg-amber-700'>
              <RotateCcw className='mr-2 h-4 w-4' />
              Retry with these fixes
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <div className='flex gap-1 rounded-2xl bg-stone-100 p-1'>
        {(
          [
            { key: 'runbook', label: 'Runbook' },
            { key: 'workspace', label: 'Workspace' },
            { key: 'simulation', label: 'Simulation' },
          ] as { key: Tab; label: string }[]
        ).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 rounded-xl px-4 py-2 text-sm font-semibold transition ${
              tab === t.key ? 'bg-white text-stone-900 shadow-sm' : 'text-stone-500 hover:text-stone-800'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'runbook' ? (
        <>
          {run.prompt ? (
            <Card className='rounded-3xl border-stone-200 bg-stone-50'>
              <CardContent className='p-5'>
                <SummaryRow icon={FileText} title='Design prompt' value={run.prompt} />
              </CardContent>
            </Card>
          ) : null}

          {run.outcome ? (
            <Card className='rounded-3xl border-emerald-200'>
              <CardHeader>
                <CardTitle className='flex items-center gap-2 text-base'>
                  {run.state === 'completed' ? (
                    <CheckCircle2 className='h-5 w-5 text-emerald-600' />
                  ) : (
                    <Clock className='h-5 w-5 text-amber-600' />
                  )}
                  Outcome — {run.outcome.status}
                  {run.outcome.spec_met === false ? ' (spec not met yet)' : ''}
                  {typeof run.outcome.steps === 'number' ? ` in ${run.outcome.steps} steps` : ''}
                  {typeof run.outcome.wall_seconds === 'number' ? ` (${Math.round(run.outcome.wall_seconds)}s)` : ''}
                </CardTitle>
              </CardHeader>
              <CardContent className='space-y-3'>
                {run.outcome.summary ? (
                  <pre className='whitespace-pre-wrap rounded-2xl bg-stone-50 p-4 text-sm leading-6 text-stone-700'>{run.outcome.summary}</pre>
                ) : null}
              </CardContent>
            </Card>
          ) : null}

          <Card className='rounded-3xl border-stone-200'>
            <CardHeader>
              <CardTitle className='text-base'>Execution log</CardTitle>
              <p className='text-sm font-normal text-stone-500'>What every step did — tool calls and their outcomes.</p>
            </CardHeader>
            <CardContent>
              <div className='max-h-96 space-y-2 overflow-y-auto pr-1'>
                {parseEvents(run.log_tail).map((ev, i) => {
                  const meta = TOOL_META[ev.title] ?? FALLBACK_META
                  return (
                    <div key={i} className='flex gap-3 rounded-2xl border border-stone-200 bg-white p-3'>
                      <span className={`mt-0.5 w-1 shrink-0 rounded-full ${meta.bar}`} aria-hidden />
                      <div className='min-w-0 flex-1'>
                        <div className='flex items-center gap-2'>
                          <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${meta.pill}`}>
                            {meta.label}
                          </span>
                          <span className='text-[11px] font-medium text-stone-400'>step {ev.step}</span>
                        </div>
                        <p className='mt-1.5 break-words text-sm leading-6 text-stone-800'>{ev.detail}</p>
                        {ev.result ? (
                          <p className={`mt-1 flex items-start gap-1.5 break-words text-xs leading-5 ${TONE_TEXT[ev.tone ?? 'neutral']}`}>
                            <span aria-hidden>{ev.tone === 'error' ? '✕' : ev.tone === 'ok' ? '✓' : '·'}</span>
                            <span>{ev.result}</span>
                          </p>
                        ) : null}
                      </div>
                    </div>
                  )
                })}
                {parseEvents(run.log_tail).length === 0 ? <p className='text-sm text-stone-500'>No events yet.</p> : null}
              </div>
            </CardContent>
          </Card>

          <Card className='rounded-3xl border-stone-200'>
            <CardHeader>
              <CardTitle className='flex items-center gap-2 text-base'>
                <ScrollText className='h-5 w-5 text-stone-500' />
                Live activity
              </CardTitle>
              <p className='text-sm font-normal text-stone-500'>Raw agent stream, refreshed live.</p>
            </CardHeader>
            <CardContent>
              <pre className='max-h-96 overflow-auto whitespace-pre-wrap rounded-2xl bg-stone-900 p-4 text-xs leading-5 text-emerald-200'>
                {run.log_tail || 'No log output yet.'}
              </pre>
            </CardContent>
          </Card>
        </>
      ) : null}

      {tab === 'workspace' ? (
        <>
        <Card className='rounded-3xl border-stone-200'>
          <CardHeader>
            <CardTitle className='text-base'>Design files</CardTitle>
          </CardHeader>
          <CardContent className='max-h-96 space-y-4 overflow-y-auto'>
            {groupedFiles.length === 0 ? <p className='text-sm text-stone-500'>No design files yet.</p> : null}
            {groupedFiles.map(([category, files]) => (
              <div key={category}>
                <p className='mb-2 text-xs font-semibold uppercase tracking-widest text-stone-400'>{category}</p>
                <div className='flex flex-wrap gap-2'>
                  {files.map((artifact) => (
                    <button
                      key={artifact}
                      onClick={() => setSelected(artifact)}
                      className={`rounded-2xl border px-3 py-1.5 text-sm transition ${
                        selected === artifact
                          ? 'border-emerald-500 bg-emerald-50 text-emerald-700'
                          : category === 'Design — schematics & symbols'
                            ? 'border-stone-200 text-emerald-700 hover:border-emerald-300'
                            : 'border-stone-200 text-stone-600 hover:border-emerald-300'
                      }`}
                    >
                      {artifact}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
        {selected ? (
          <Card className='rounded-3xl border-stone-200'>
            <CardHeader>
              <CardTitle className='flex items-center justify-between gap-2 text-base'>
                <span className='truncate'>{selected}</span>
                <span className='flex shrink-0 items-center gap-2'>
                  {selected.endsWith('.sch') ? (
                    <Button
                      size='sm'
                      className='h-8 rounded-xl bg-emerald-600 px-3 text-xs hover:bg-emerald-700'
                      onClick={async () => {
                        try {
                          const { opened } = await openInXschem(run.run_id, selected)
                          toast({ title: 'xschem GUI launched', description: `${opened} opened (fresh window with the current file).` })
                        } catch (err) {
                          toast({ title: 'Could not open xschem', description: err instanceof Error ? err.message : 'Unknown error', variant: 'destructive' })
                        }
                      }}
                    >
                      <AppWindow className='mr-1.5 h-3.5 w-3.5' />
                      Open in xschem
                    </Button>
                  ) : null}
                  <a href={artifactUrl(run.run_id, selected)} target='_blank' rel='noreferrer' className='text-xs font-normal text-emerald-600 hover:underline'>open raw</a>
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {/\.(png|jpe?g|webp|gif)$/i.test(selected) ? (
                <img src={artifactUrl(run.run_id, selected)} alt={selected} className='max-h-[600px] rounded-2xl border border-stone-200' />
              ) : selected.toLowerCase().endsWith('.pdf') ? (
                <iframe src={artifactUrl(run.run_id, selected)} title={selected} className='h-[600px] w-full rounded-2xl border border-stone-200' />
              ) : selected.toLowerCase().endsWith('.raw') ? (
                <p className='text-sm text-stone-500'>Binary rawfile — see Simulation tab for waveforms.</p>
              ) : (
                <pre className='max-h-[600px] overflow-auto whitespace-pre-wrap rounded-2xl bg-stone-900 p-4 text-xs leading-5 text-emerald-200'>{fileText || 'Loading…'}</pre>
              )}
            </CardContent>
          </Card>
        ) : null}
        </>
      ) : null}

      {tab === 'simulation' ? (
        <>
          {run.outcome?.evidence ? (
            <Card className='rounded-3xl border-emerald-200'>
              <CardHeader>
                <CardTitle className='flex items-center gap-2 text-base'>
                  <Activity className='h-5 w-5 text-emerald-600' />
                  Simulation evidence
                </CardTitle>
              </CardHeader>
              <CardContent>
                <pre className='whitespace-pre-wrap rounded-2xl bg-emerald-50 p-4 text-sm leading-6 text-emerald-900'>{run.outcome.evidence}</pre>
              </CardContent>
            </Card>
          ) : null}
          {(run.plots ?? []).length > 0 ? (
            <Card className='rounded-3xl border-stone-200'>
              <CardHeader>
                <CardTitle className='flex items-center gap-2 text-base'>
                  <Waves className='h-5 w-5 text-emerald-600' />
                  Waveforms
                </CardTitle>
              </CardHeader>
              <CardContent className='space-y-4'>
                {(run.plots ?? []).map((plot) => (
                  <img
                    key={plot}
                    src={artifactUrl(run.run_id, plot)}
                    alt={plot}
                    className='w-full rounded-2xl border border-stone-200 bg-white'
                  />
                ))}
              </CardContent>
            </Card>
          ) : (
            <Card className='rounded-3xl border-stone-200'>
              <CardContent className='p-6 text-sm text-stone-500'>No waveforms yet — plots appear once a simulation produces rawfiles.</CardContent>
            </Card>
          )}
        </>
      ) : null}
    </div>
  )
}
