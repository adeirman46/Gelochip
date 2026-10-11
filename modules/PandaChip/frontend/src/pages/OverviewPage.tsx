import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Activity, CheckCircle2, ChevronLeft, ChevronRight, CircuitBoard, Search, Trash2 } from 'lucide-react'

import { deleteRun, listRuns, type RunState, type RunSummary } from '@/api/runs'
import { EmptyState, ErrorState, LoadingState } from '@/components/app/shared'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

const PAGE_SIZE = 8

const stateBadge: Record<RunState, string> = {
  completed: 'bg-emerald-100 text-emerald-700',
  running: 'bg-sky-100 text-sky-700',
  paused: 'bg-violet-100 text-violet-700',
  needs_review: 'bg-amber-100 text-amber-700',
  failed: 'bg-rose-100 text-rose-700',
}

function MetricTile({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <Card className='rounded-3xl border-stone-200'>
      <CardContent className='p-5'>
        <p className='text-xs font-semibold uppercase tracking-widest text-stone-400'>{label}</p>
        <p className={`mt-2 text-3xl font-semibold ${tone}`}>{value}</p>
      </CardContent>
    </Card>
  )
}

export function OverviewPage() {
  const navigate = useNavigate()
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)

  async function refresh() {
    try {
      setRuns(await listRuns())
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load runs')
    }
  }

  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), 4000)
    return () => clearInterval(timer)
  }, [])

  const filtered = useMemo(() => {
    if (!runs) {
      return []
    }
    const q = query.trim().toLowerCase()
    if (!q) {
      return runs
    }
    return runs.filter((r) =>
      [r.run_id, r.prompt, r.state, r.model ?? '', r.pdk ?? ''].some((v) => v.toLowerCase().includes(q)),
    )
  }, [runs, query])

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const current = Math.min(page, pages)
  const visible = filtered.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE)

  if (error) {
    return <ErrorState title='Could not load design runs' detail={error} onRetry={() => void refresh()} />
  }
  if (runs === null) {
    return <LoadingState label='Loading PandaChip design runs…' />
  }

  const doneCount = runs.filter((r) => r.state === 'completed').length
  const runningCount = runs.filter((r) => r.state === 'running' || r.state === 'paused').length

  return (
    <div className='space-y-4'>
      <div>
        <h2 className='text-2xl font-semibold text-stone-900'>Run dashboard</h2>
        <p className='mt-1 text-sm text-stone-500'>
          Live view of design runs with search, pagination, and direct navigation into run detail.
        </p>
      </div>

      <div className='grid gap-3 sm:grid-cols-3'>
        <MetricTile label='Total runs' value={runs.length} tone='text-stone-900' />
        <MetricTile label='Verified done' value={doneCount} tone='text-emerald-600' />
        <MetricTile label='Running now' value={runningCount} tone='text-sky-600' />
      </div>

      <Card className='rounded-3xl border-stone-200'>
        <CardContent className='p-5'>
          <div className='flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between'>
            <div>
              <h3 className='text-lg font-semibold text-stone-900'>Overview console</h3>
              <p className='text-sm text-stone-500'>Runs are loaded live and filtered locally for quick search.</p>
            </div>
            <div className='relative w-full sm:w-72'>
              <Search className='pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400' />
              <Input
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value)
                  setPage(1)
                }}
                placeholder='Search run, prompt, model, or state'
                className='h-10 rounded-2xl border-stone-200 pl-9'
              />
            </div>
          </div>

          {filtered.length === 0 ? (
            <div className='mt-4'>
              <EmptyState
                title={query ? 'No runs match the search' : 'No design runs yet'}
                detail={query ? 'Try a different query.' : 'Start your first analog design from "New Analog Design".'}
              />
            </div>
          ) : (
            <div className='mt-4 overflow-x-auto'>
              <table className='w-full min-w-[720px] text-left text-sm'>
                <thead>
                  <tr className='border-b border-stone-200 text-xs uppercase tracking-widest text-stone-400'>
                    <th className='py-3 pr-4 font-semibold'>Run</th>
                    <th className='py-3 pr-4 font-semibold'>Model</th>
                    <th className='py-3 pr-4 font-semibold'>PDK</th>
                    <th className='py-3 pr-4 font-semibold'>Created</th>
                    <th className='py-3 pr-4 font-semibold'>Status</th>
                    <th className='py-3 font-semibold'></th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((run) => (
                    <tr
                      key={run.run_id}
                      onClick={() => navigate(`/designs/${run.run_id}`)}
                      className='cursor-pointer border-b border-stone-100 transition hover:bg-emerald-50/40'
                    >
                      <td className='max-w-md py-3 pr-4'>
                        <p className='font-semibold text-stone-900'>{run.run_id}</p>
                        <p className='truncate text-xs text-stone-500'>
                          {run.prompt || 'CLI-launched run (task file in the workspace).'}
                        </p>
                      </td>
                      <td className='py-3 pr-4 text-stone-600'>{run.model || '—'}</td>
                      <td className='py-3 pr-4 text-stone-600'>{run.pdk || '—'}</td>
                      <td className='py-3 pr-4 text-stone-500'>{run.created || '—'}</td>
                      <td className='py-3 pr-4'>
                        <Badge className={`rounded-full px-3 py-1 ${stateBadge[run.state] ?? stateBadge.needs_review}`}>
                          {run.state.replace('_', ' ')}
                        </Badge>
                      </td>
                      <td className='py-3'>
                        <button
                          aria-label={`Delete ${run.run_id}`}
                          onClick={async (event) => {
                            event.stopPropagation()
                            if (window.confirm(`Delete run "${run.run_id}" and all its artifacts?`)) {
                              try {
                                await deleteRun(run.run_id)
                              } catch {
                                /* refresh shows reality either way */
                              }
                              void refresh()
                            }
                          }}
                          className='rounded-xl p-2 text-stone-400 transition hover:bg-rose-50 hover:text-rose-500'
                        >
                          <Trash2 className='h-4 w-4' />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className='mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between'>
            <p className='flex items-center gap-2 text-xs text-stone-500'>
              <CircuitBoard className='h-3.5 w-3.5' />
              Showing {filtered.length === 0 ? 0 : (current - 1) * PAGE_SIZE + 1}-
              {Math.min(current * PAGE_SIZE, filtered.length)} of {filtered.length} runs
              <CheckCircle2 className='ml-3 h-3.5 w-3.5 text-emerald-500' /> {doneCount} verified
              <Activity className='ml-3 h-3.5 w-3.5 text-sky-500' /> {runningCount} running
            </p>
            <div className='flex items-center gap-2'>
              <Button
                variant='outline'
                disabled={current <= 1}
                onClick={() => setPage(current - 1)}
                className='rounded-2xl border-stone-200'
              >
                <ChevronLeft className='mr-1 h-4 w-4' />
                Previous
              </Button>
              <span className='text-sm text-stone-500'>
                Page {current} / {pages}
              </span>
              <Button
                variant='outline'
                disabled={current >= pages}
                onClick={() => setPage(current + 1)}
                className='rounded-2xl border-stone-200'
              >
                Next
                <ChevronRight className='ml-1 h-4 w-4' />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
