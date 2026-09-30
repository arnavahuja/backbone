import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import * as echarts from 'echarts'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { ApiError } from '@/api/client'
import { router } from '@/router'
import { ECHARTS_THEME_NAME, echartsTheme } from '@/theme/echartsTheme'
import './index.css'

echarts.registerTheme(ECHARTS_THEME_NAME, echartsTheme)

const MAX_RETRIES = 2

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (count, error) =>
        !(error instanceof ApiError && error.status < 500) && count < MAX_RETRIES,
    },
  },
})

const root = document.getElementById('root')
if (!root) throw new Error('Root element missing')

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
