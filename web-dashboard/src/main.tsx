import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { installEditTracker, installPreloadErrorListener } from './chunkRecovery'
import './styles.css'
import './visual-refresh.css'

installPreloadErrorListener()
installEditTracker()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
