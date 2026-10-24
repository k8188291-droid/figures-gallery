import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { loadModelList } from './modelList'
import './index.css'

loadModelList().then((models) => {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <App models={models} />
    </React.StrictMode>,
  )
})

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', async () => {
    const registration = await navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`, {
      scope: import.meta.env.BASE_URL,
      updateViaCache: 'none',
    })
    await navigator.serviceWorker.ready
    ;(registration.active ?? navigator.serviceWorker.controller)?.postMessage({ type: 'CHECK_INDEX' })
  })
}
