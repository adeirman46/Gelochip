import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import {
  Activity,
  Bot,
  ChevronRight,
  CircuitBoard,
  Cog,
  LayoutGrid,
  LogOut,
  Moon,
  PawPrint,
  Sparkles,
  Sun,
  Waypoints,
} from 'lucide-react'

import { useAuth } from '@/auth/AuthProvider'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

const navItems: {
  key: 'overview' | 'create' | 'detail' | 'settings'
  label: string
  icon: typeof LayoutGrid
  to: string
  isActive: (pathname: string) => boolean
}[] = [
  {
    key: 'overview',
    label: 'Design Runs',
    icon: LayoutGrid,
    to: '/overview',
    isActive: (pathname) => pathname === '/overview',
  },
  {
    key: 'create',
    label: 'New Analog Design',
    icon: Sparkles,
    to: '/designs/new',
    isActive: (pathname) => pathname === '/designs/new',
  },
  {
    key: 'detail',
    label: 'Run Detail & Evidence',
    icon: Waypoints,
    to: '/overview',
    isActive: (pathname) => pathname.startsWith('/designs/') && pathname !== '/designs/new',
  },
  {
    key: 'settings',
    label: 'Settings',
    icon: Cog,
    to: '/settings',
    isActive: (pathname) => pathname === '/settings',
  },
]

// The last run the user opened, so "Run Detail & Evidence" works from ANY page.
function currentRunId(pathname: string): string {
  if (!pathname.startsWith('/designs/') || pathname === '/designs/new') {
    return ''
  }
  const [, , runId] = pathname.split('/')
  return runId ?? ''
}

function getDetailTarget(pathname: string) {
  const runId = currentRunId(pathname) || localStorage.getItem('pc-last-run') || ''
  return runId ? `/designs/${runId}` : '/overview'
}

function useDarkMode(): [boolean, () => void] {
  const [dark, setDark] = useState(() => localStorage.getItem('pc-theme') === 'dark')

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    localStorage.setItem('pc-theme', dark ? 'dark' : 'light')
  }, [dark])

  return [dark, () => setDark((value) => !value)]
}

export function ShellLayout() {
  const { pathname } = useLocation()
  const { user, logout } = useAuth()
  const [dark, toggleDark] = useDarkMode()

  useEffect(() => {
    const runId = currentRunId(pathname)
    if (runId) {
      localStorage.setItem('pc-last-run', runId)
    }
  }, [pathname])

  return (
    <div className='min-h-screen bg-stone-100 text-stone-800'>
      <div className='flex min-h-screen w-full gap-3 p-2 sm:gap-4 sm:p-3 lg:p-4'>
        <aside className='hidden w-72 shrink-0 rounded-3xl bg-white p-4 shadow-xl lg:flex lg:flex-col'>
          <div className='rounded-3xl bg-stone-50 p-4'>
            <div className='flex items-start justify-between gap-3'>
              <div>
                <p className='text-xs font-semibold uppercase tracking-widest text-stone-400'>AI-native analog design</p>
                <h1 className='mt-2 text-3xl font-semibold tracking-tight text-emerald-600'>PandaChip</h1>
              </div>
              <div className='flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-lime-400 text-white shadow-lg'>
                <PawPrint className='h-6 w-6' />
              </div>
            </div>

            <div className='mt-4 rounded-3xl bg-gradient-to-br from-emerald-600 via-emerald-500 to-lime-400 p-4 text-white shadow-xl'>
              <p className='text-xs font-medium uppercase tracking-widest text-emerald-100'>AI-native analog chip design</p>
              <h2 className='mt-3 text-2xl font-semibold leading-8'>From prompt to xschem validation to GDS through gLayout.</h2>
              <p className='mt-4 text-sm leading-6 text-emerald-50'>
                Every run yields a schematic, a netlist, transient/AC waveforms, and FFT evidence — with layout and DRC/LVS sign-off as the road ahead.
              </p>
            </div>
          </div>

          <div className='mt-4 rounded-3xl bg-stone-50 p-3'>
            {navItems.map((item) => {
              const Icon = item.icon
              const active = item.isActive(pathname)
              const target = item.key === 'detail' ? getDetailTarget(pathname) : item.to

              return (
                <NavLink
                  key={item.key}
                  to={target}
                  className={`mb-2 flex w-full items-center justify-between rounded-2xl px-3 py-3 text-left transition-all ${
                    active
                      ? 'bg-white text-stone-900 shadow-sm ring-1 ring-stone-200'
                      : 'text-stone-500 hover:bg-white/80 hover:text-stone-800'
                  }`}
                >
                  <div className='flex items-center gap-3'>
                    <div
                      className={`flex h-9 w-9 items-center justify-center rounded-xl ${
                        active ? 'bg-emerald-50 text-emerald-600' : 'bg-stone-200 text-stone-500'
                      }`}
                    >
                      <Icon className='h-4 w-4' />
                    </div>
                    <div className='text-sm font-semibold'>{item.label}</div>
                  </div>
                  <ChevronRight className={`h-4 w-4 ${active ? 'text-emerald-500' : 'text-stone-300'}`} />
                </NavLink>
              )
            })}
          </div>

          <div className='mt-auto'>
            <div className='rounded-3xl border-0 bg-stone-50 p-4 shadow-none'>
              <div className='flex items-center justify-between gap-3'>
                <div className='min-w-0'>
                  <h3 className='truncate text-sm font-semibold text-stone-700'>{user?.fullName ?? 'Authenticated user'}</h3>
                  <p className='truncate text-sm text-stone-500'>{user?.username ?? 'Unknown user'}</p>
                </div>
                <div className='flex shrink-0 items-center gap-2'>
                  <Button
                    variant='outline'
                    onClick={toggleDark}
                    className='rounded-2xl border-stone-200 px-3'
                    aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
                  >
                    {dark ? <Sun className='h-4 w-4' /> : <Moon className='h-4 w-4' />}
                  </Button>
                  <Button variant='outline' onClick={logout} className='rounded-2xl border-stone-200'>
                    <LogOut className='mr-2 h-4 w-4' />
                    Sign out
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </aside>

        <main className='flex-1 space-y-4'>
          <section className='rounded-3xl bg-white px-5 py-5 shadow-xl sm:px-6'>
            <div className='flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between'>
              <div className='max-w-3xl'>
                <p className='text-sm font-medium text-stone-400'>Analog design operations console</p>
                <h2 className='mt-2 text-3xl font-semibold tracking-tight text-stone-900 sm:text-4xl'>PandaChip analog IC platform</h2>
                <p className='mt-3 max-w-3xl text-sm leading-6 text-stone-500 sm:text-base'>
                  Send a design prompt, follow the agent as it draws and simulates the circuit, then open the result in the xschem GUI with waveforms embedded.
                </p>
              </div>
              <div className='flex flex-wrap items-center gap-2 xl:justify-end'>
                <Badge className='rounded-full bg-emerald-100 px-3 py-1 text-emerald-700 hover:bg-emerald-100'>
                  <Bot className='mr-1.5 h-3.5 w-3.5' />
                  Ollama + Gemini
                </Badge>
                <Badge className='rounded-full bg-lime-100 px-3 py-1 text-lime-700 hover:bg-lime-100'>
                  <CircuitBoard className='mr-1.5 h-3.5 w-3.5' />
                  xschem + ngspice
                </Badge>
                <Badge className='rounded-full bg-amber-100 px-3 py-1 text-amber-700 hover:bg-amber-100'>
                  <Activity className='mr-1.5 h-3.5 w-3.5' />
                  OpenADA evidence
                </Badge>
              </div>
            </div>
          </section>

          <section className='rounded-3xl bg-white p-4 shadow-xl sm:p-5'>
            <Outlet />
          </section>
        </main>
      </div>
    </div>
  )
}
