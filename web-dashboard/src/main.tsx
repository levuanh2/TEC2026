import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { installPreloadErrorListener } from './chunkRecovery'
import './styles.css'

installPreloadErrorListener()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
