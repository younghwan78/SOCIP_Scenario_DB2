import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { ChartTipProvider } from './components/ChartTip'
import './styles.css'

createRoot(document.getElementById('root')!).render(<StrictMode><ChartTipProvider><App /></ChartTipProvider></StrictMode>)
