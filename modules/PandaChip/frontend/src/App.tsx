import { Navigate, Route, Routes } from 'react-router-dom'

import { useAuth } from '@/auth/AuthProvider'
import { LoadingState } from '@/components/app/shared'
import { ShellLayout } from '@/components/app/ShellLayout'
import { CreateDesignPage } from '@/pages/CreateDesignPage'
import { LoginPage } from '@/pages/LoginPage'
import { OverviewPage } from '@/pages/OverviewPage'
import { RunDetailPage } from '@/pages/RunDetailPage'
import { SettingsPage } from '@/pages/SettingsPage'

import './App.css'

function App() {
  const { status } = useAuth()

  if (status === 'checking') {
    return (
      <div className='min-h-screen bg-stone-100 p-4'>
        <LoadingState label='Checking your PandaChip session…' />
      </div>
    )
  }

  if (status === 'unauthenticated') {
    return <LoginPage />
  }

  return (
    <Routes>
      <Route path='/' element={<Navigate to='/overview' replace />} />
      <Route element={<ShellLayout />}>
        <Route path='/overview' element={<OverviewPage />} />
        <Route path='/designs/new' element={<CreateDesignPage />} />
        <Route path='/designs/:id' element={<RunDetailPage />} />
        <Route path='/settings' element={<SettingsPage />} />
      </Route>
      <Route path='*' element={<Navigate to='/overview' replace />} />
    </Routes>
  )
}

export default App
