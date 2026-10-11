import { Bot, Box, CircuitBoard, Cpu, FlaskConical, FolderGit2 } from 'lucide-react'

import { SummaryRow } from '@/components/app/shared'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function SettingsPage() {
  return (
    <div className='space-y-4'>
      <Card className='rounded-3xl border-stone-200'>
        <CardHeader>
          <CardTitle>Runtime environment</CardTitle>
          <CardDescription>
            Fixed local configuration of this PandaChip workstation — local Ollama models plus Google Gemini via Application Default Credentials.
          </CardDescription>
        </CardHeader>
        <CardContent className='grid gap-5 sm:grid-cols-2'>
          <SummaryRow icon={Bot} title='LLM' value='Local Ollama server + Google Gemini (Vertex AI, ADC) — model selected per run' />
          <SummaryRow icon={CircuitBoard} title='PDK' value='GF180MCU-D, 3.3 V devices (nfet_03v3 / pfet_03v3)' />
          <SummaryRow icon={Box} title='EDA runtime' value='IIC-OSIC-TOOLS container "pandachip-eda" — xschem 3.4.8, ngspice 46' />
          <SummaryRow icon={FlaskConical} title='Contract' value='OpenADA 0.4.0 (vendored in src/) for netlist + simulation evidence' />
          <SummaryRow icon={Cpu} title='Agent' value='pandachip/agent.py — write .sch, netlist, simulate, FFT/AC verify' />
          <SummaryRow icon={FolderGit2} title='Workspaces' value='designs/<run-id>/ — schematic, netlist, raws, transcript, outcome' />
        </CardContent>
      </Card>

      <Card className='rounded-3xl border-stone-200 bg-stone-50'>
        <CardHeader>
          <CardTitle className='text-base'>Handy commands</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className='overflow-auto rounded-2xl bg-stone-900 p-4 text-xs leading-6 text-emerald-200'>
{`scripts/start_web.sh                 # this UI (Go server, port 8317)
scripts/start_eda_container.sh       # (re)start the EDA container
scripts/xschem_gui.sh <sch> [raw]    # open any schematic on the display
.venv/bin/python -m pandachip.agent --task-file <task.md> --workdir designs/<name>`}
          </pre>
        </CardContent>
      </Card>
    </div>
  )
}
