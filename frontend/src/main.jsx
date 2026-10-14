import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Bootstrap is imported inside tailwind.css, in its own cascade layer.
import './tailwind.css'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
