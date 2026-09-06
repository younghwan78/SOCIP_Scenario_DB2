import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { installScenarioUrlSync } from './store/urlState'

const stopUrlSync = installScenarioUrlSync()
if (import.meta.hot) import.meta.hot.dispose(stopUrlSync)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
