import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, CircuitBoard, Paperclip, Rocket, Sparkles, X } from 'lucide-react'

import { listModels, listPdks, startRun } from '@/api/runs'
import { ErrorState, Field } from '@/components/app/shared'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

const examples = [
  {
    label: 'Double balanced mixer',
    prompt:
      'Design a double balanced mixer (Gilbert cell) on GF180MCU 3.3V devices. RF = 5 MHz differential small signal, LO = 4 MHz differential large signal. Verify with a 10 us transient: the 1 MHz and 9 MHz mixing products must dominate RF/LO feedthrough at the differential IF output.',
  },
  {
    label: 'LNA 50 dB @ 40 MHz',
    prompt:
      'Design a multi-stage LNA with at least 50 dB small-signal gain at 40 MHz on GF180MCU 3.3V devices, in one schematic. Verify with both .ac (gain at 40 MHz) and .tran (1 mV 40 MHz input, expect >0.25 V output).',
  },
  {
    label: 'Ring oscillator LO',
    prompt:
      'Design a 5-stage CMOS ring oscillator local oscillator on GF180MCU 3.3V devices targeting 20-200 MHz. Verify sustained rail-to-rail oscillation with a transient simulation and report the frequency from the FFT.',
  },
]

const selectClass =
  'h-11 w-full rounded-2xl border border-stone-200 bg-white px-3 text-sm text-stone-800 outline-none focus:border-emerald-400'

// GF180MCU device families; the choice is appended to the task as an
// explicit constraint so the agent picks the right transistors.
const gf180Voltages = [
  { value: '3.3', label: '3.3 V (nfet_03v3 / pfet_03v3)', instruction: 'Use GF180MCU 3.3V devices (nfet_03v3 / pfet_03v3) with VDD = 3.3V.' },
  { value: '5.0', label: '5.0 V (nfet_05v0 / pfet_05v0)', instruction: 'Use GF180MCU 5.0V devices (nfet_05v0 / pfet_05v0) with VDD = 5.0V.' },
  { value: '6.0', label: '6.0 V thick-oxide (nfet_06v0 / pfet_06v0)', instruction: 'Use GF180MCU 6.0V thick-oxide devices (nfet_06v0 / pfet_06v0) with VDD = 6.0V.' },
]

export function CreateDesignPage() {
  const navigate = useNavigate()
  const fileInput = useRef<HTMLInputElement>(null)
  const [prompt, setPrompt] = useState('')
  const [name, setName] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [model, setModel] = useState('')
  const [pdks, setPdks] = useState<string[]>([])
  const [pdk, setPdk] = useState('')
  const [pdkNote, setPdkNote] = useState('')
  const [voltage, setVoltage] = useState('3.3')
  const [files, setFiles] = useState<File[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        const m = await listModels()
        setModels(m.models)
        setModel((current) => current || m.default)
      } catch {
        setModels([])
      }
      try {
        const p = await listPdks()
        setPdks(p.pdks)
        setPdk((current) => current || p.default)
        setPdkNote(p.note ?? '')
      } catch {
        setPdks([])
      }
    })()
  }, [])

  function addFiles(list: FileList | null) {
    if (!list) {
      return
    }
    // Materialize before touching the input: FileList is live and clearing
    // the input value would empty it before the state updater runs.
    const picked = Array.from(list)
    if (picked.length === 0) {
      return
    }
    setFiles((current) => [...current, ...picked])
    if (fileInput.current) {
      fileInput.current.value = ''
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const voltageInstruction = pdk.startsWith('gf180')
        ? gf180Voltages.find((v) => v.value === voltage)?.instruction
        : undefined
      const fullPrompt = voltageInstruction ? `${prompt.trim()}\n\n${voltageInstruction}` : prompt.trim()
      const { run_id } = await startRun(fullPrompt, {
        name: name.trim() || undefined,
        model: model || undefined,
        pdk: pdk || undefined,
        files,
      })
      navigate(`/designs/${run_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to start the design run')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className='space-y-4'>
      {error ? <ErrorState title='Run could not start' detail={error} /> : null}

      <Card className='rounded-3xl border-stone-200'>
        <CardHeader>
          <CardTitle className='flex items-center gap-2'>
            <Sparkles className='h-5 w-5 text-emerald-600' />
            Describe the analog circuit
          </CardTitle>
          <CardDescription>
            The selected model (local Ollama or Google Gemini) draws the xschem schematic on the chosen PDK, netlists and simulates it through
            OpenADA, and keeps iterating until the waveform evidence matches your spec.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className='space-y-5' onSubmit={handleSubmit}>
            <Field label='Design prompt' hint='Circuit, key specs, and the verification you expect. Paste or drop reference images/PDFs directly here.'>
              <Textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                onPaste={(event) => {
                  const pasted = Array.from(event.clipboardData?.files ?? [])
                  if (pasted.length > 0) {
                    event.preventDefault()
                    setFiles((current) => [...current, ...pasted])
                  }
                }}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault()
                  const dropped = Array.from(event.dataTransfer?.files ?? [])
                  if (dropped.length > 0) {
                    setFiles((current) => [...current, ...dropped])
                  }
                }}
                placeholder='e.g. Design a two-stage op-amp with 60 dB DC gain; verify gain and bandwidth with an AC sweep… (paste an image here to attach it)'
                className='min-h-40 rounded-2xl border-stone-200'
                required
              />
            </Field>

            <div className='grid gap-5 sm:grid-cols-2'>
              <Field label='Model' hint='Local Ollama models, plus Google Gemini (Vertex AI) when ADC is configured.'>
                <div className='relative'>
                  <Bot className='pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400' />
                  <select value={model} onChange={(event) => setModel(event.target.value)} className={`${selectClass} pl-9`}>
                    {models.length === 0 ? <option value=''>No models available</option> : null}
                    {models.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </div>
              </Field>

              <Field label='PDK' hint={pdkNote || 'Process design kits detected in the EDA container.'}>
                <div className='relative'>
                  <CircuitBoard className='pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400' />
                  <select value={pdk} onChange={(event) => setPdk(event.target.value)} className={`${selectClass} pl-9`}>
                    {pdks.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </div>
              </Field>
            </div>

            {pdk.startsWith('gf180') ? (
              <Field label='Device voltage' hint='Transistor family the agent must use (and the matching VDD).'>
                <select value={voltage} onChange={(event) => setVoltage(event.target.value)} className={selectClass}>
                  {gf180Voltages.map((v) => (
                    <option key={v.value} value={v.value}>
                      {v.label}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}

            <Field label='Reference files (optional)' hint='Images go to the model when it is multimodal; PDF/text content is inlined into the task.'>
              <div className='space-y-2'>
                <input
                  ref={fileInput}
                  type='file'
                  multiple
                  accept='image/*,.pdf,.txt,.md,.csv,.cir,.spice,.sch'
                  onChange={(event) => addFiles(event.target.files)}
                  className='hidden'
                  id='ref-files'
                />
                <Button
                  type='button'
                  variant='outline'
                  onClick={() => fileInput.current?.click()}
                  className='rounded-2xl border-stone-200'
                >
                  <Paperclip className='mr-2 h-4 w-4' />
                  Attach image / PDF / text
                </Button>
                {files.length > 0 ? (
                  <div className='flex flex-wrap gap-2'>
                    {files.map((file, index) => (
                      <span
                        key={`${file.name}-${index}`}
                        className='inline-flex items-center gap-1.5 rounded-2xl border border-stone-200 bg-white px-3 py-1 text-xs text-stone-700'
                      >
                        {file.name}
                        <button
                          type='button'
                          aria-label={`Remove ${file.name}`}
                          onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}
                          className='text-stone-400 hover:text-rose-500'
                        >
                          <X className='h-3.5 w-3.5' />
                        </button>
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </Field>

            <Field label='Run name (optional)' hint='Letters, digits, dot, dash, underscore. Auto-generated when empty.'>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder='e.g. opamp-60db'
                pattern='[A-Za-z0-9._-]*'
                className='h-11 rounded-2xl border-stone-200'
              />
            </Field>

            <Button type='submit' disabled={submitting || !prompt.trim()} className='h-11 rounded-2xl bg-emerald-600 px-6 hover:bg-emerald-700'>
              <Rocket className='mr-2 h-4 w-4' />
              {submitting ? 'Starting…' : 'Design it'}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card className='rounded-3xl border-stone-200 bg-stone-50'>
        <CardHeader>
          <CardTitle className='text-base'>Example prompts</CardTitle>
          <CardDescription>Click to prefill — these three are verified end-to-end on this workstation.</CardDescription>
        </CardHeader>
        <CardContent className='flex flex-wrap gap-2'>
          {examples.map((example) => (
            <button
              key={example.label}
              type='button'
              onClick={() => setPrompt(example.prompt)}
              className='rounded-2xl border border-stone-200 bg-white px-4 py-2 text-sm font-medium text-stone-700 transition hover:border-emerald-300 hover:text-emerald-700'
            >
              {example.label}
            </button>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
