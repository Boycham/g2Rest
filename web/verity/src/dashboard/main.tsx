import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { startSentry } from '../../../client.js'
import '../shared/tokens.css'
import './dashboard.css'
import App from './App'
import { store } from './backend'

startSentry('dashboard')
store.start()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
