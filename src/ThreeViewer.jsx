import { useEffect, useRef, useState } from 'react'
import { createGalleryRuntime } from './galleryRuntime'
import { STUDIO_DEFAULTS } from './studioLook'

const CDN = 'https://cdn.jsdelivr.net/npm/three@0.179.1'
const modulesPromise = Promise.all([
  import(/* @vite-ignore */ `${CDN}/build/three.module.js`),
  import(/* @vite-ignore */ `${CDN}/examples/jsm/loaders/GLTFLoader.js`),
  import(/* @vite-ignore */ `${CDN}/examples/jsm/controls/OrbitControls.js`),
  import(/* @vite-ignore */ `${CDN}/examples/jsm/libs/meshopt_decoder.module.js`),
])

// `null` selects the procedural neutral studio (model-viewer's "neutral").
const environments = {
  Studio: null,
  'Studio HDRI': 'studio.webp',
  Beach: 'beach.webp',
  Desert: 'desert.webp',
  Forest: 'forest.webp',
  Interior: 'interior.webp',
  Night: 'night.webp',
}

const environmentUrl = (name) => environments[name] ? `${import.meta.env.BASE_URL}enviroments/${environments[name]}` : null
const environmentPreview = (name) => environments[name]
  ? `url(${environmentUrl(name)})`
  : 'radial-gradient(ellipse at 50% 15%, #ffffff 0%, #d9d9d9 28%, #9a9a9a 62%, #5c5c5c 100%)'

function Slider({ label, value, min, max, step, onChange, format = (number) => number.toFixed(2) }) {
  return (
    <>
      <label className="mt-4 block text-[11px] text-white/40">{label} <span className="float-right text-white/65">{format(value)}</span></label>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} className="mt-2 w-full accent-acid" />
    </>
  )
}

function Toggle({ label, value, onChange }) {
  return (
    <div className="mt-4 flex items-center justify-between text-[11px] text-white/40">
      <span>{label}</span>
      <button type="button" aria-pressed={value} onClick={() => onChange((current) => !current)} className={`relative h-5 w-9 rounded-full transition ${value ? 'bg-acid' : 'bg-white/15'}`}><span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition ${value ? 'left-[18px]' : 'left-0.5'}`} /></button>
    </div>
  )
}

function EnvironmentPanel({ open, onClose, environment, setEnvironment, strength, setStrength, rotation, setRotation, autoRotate, setAutoRotate, look, setLook }) {
  const updateLook = (key) => (value) => setLook((current) => ({ ...current, [key]: typeof value === 'function' ? value(current[key]) : value }))
  return (
    <div className={`absolute right-4 top-[164px] z-20 max-h-[calc(100%-180px)] w-[260px] overflow-y-auto rounded-2xl border border-white/10 bg-[#17181b]/95 p-4 text-white shadow-2xl backdrop-blur-xl transition ${open ? 'translate-x-0 opacity-100' : 'pointer-events-none translate-x-3 opacity-0'}`}>
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold">Environment Settings</h3>
        <button type="button" onClick={onClose} className="text-lg text-white/40 hover:text-white">×</button>
      </div>
      <p className="mt-4 text-[11px] text-white/35">HDRI</p>
      <div className="mt-2 h-24 rounded-lg border border-white/10 bg-cover bg-center" style={{ backgroundImage: environmentPreview(environment) }} />
      <label className="mt-4 block text-[11px] text-white/40">Surrounding</label>
      <select value={environment} onChange={(event) => setEnvironment(event.target.value)} className="mt-2 w-full rounded-lg border border-white/10 bg-[#1d1e22] px-3 py-2.5 text-xs outline-none focus:border-acid/60">
        {Object.keys(environments).map((name) => <option key={name}>{name}</option>)}
      </select>
      <Slider label="Strength" value={strength} min="0" max="3" step="0.1" onChange={setStrength} format={(number) => number.toFixed(1)} />
      <Slider label="Rotation" value={rotation} min="0" max="360" step="1" onChange={setRotation} format={(number) => `${number}°`} />
      <Toggle label="Auto Rotate" value={autoRotate} onChange={setAutoRotate} />
      <p className="mt-5 border-t border-white/10 pt-4 text-[11px] text-white/35">Look</p>
      <label className="mt-3 block text-[11px] text-white/40">Tone mapping</label>
      <select value={look.toneMapping} onChange={(event) => updateLook('toneMapping')(event.target.value)} className="mt-2 w-full rounded-lg border border-white/10 bg-[#1d1e22] px-3 py-2.5 text-xs outline-none focus:border-acid/60">
        <option value="neutral">PBR Neutral</option>
        <option value="aces">ACES Filmic</option>
      </select>
      <Slider label="Exposure" value={look.exposure} min="0.3" max="2.5" step="0.05" onChange={updateLook('exposure')} />
      <Slider label="Shadow intensity" value={look.shadowIntensity} min="0" max="2" step="0.05" onChange={updateLook('shadowIntensity')} />
      <Slider label="Shadow softness" value={look.shadowSoftness} min="0" max="1" step="0.05" onChange={updateLook('shadowSoftness')} />
      <Toggle label="Fill lights" value={look.fillLights} onChange={updateLook('fillLights')} />
    </div>
  )
}

const formatMB = (bytes) => (bytes / 1048576).toFixed(1)

function LoadingOverlay({ progress }) {
  const { loaded, total } = progress
  const known = total > 0
  const fraction = known ? Math.min(loaded / total, 1) : 0
  const downloaded = known && loaded >= total
  const label = downloaded ? 'Preparing model' : known ? `Loading model · ${Math.floor(fraction * 100)}%` : 'Loading model'
  return (
    <div className="pointer-events-none absolute inset-0 z-[5] grid place-items-center bg-ink/65 backdrop-blur-sm" role="status" aria-live="polite">
      <div className="flex w-[min(280px,70%)] flex-col items-center gap-3">
        <span className="text-[10px] font-semibold uppercase tracking-[.28em] text-white/55">{label}</span>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={known ? Math.floor(fraction * 100) : undefined}>
          {known && !downloaded
            ? <div className="h-full rounded-full bg-acid transition-[width] duration-200" style={{ width: `${fraction * 100}%` }} />
            : <div className="h-full w-1/3 animate-[loading-slide_1.2s_ease-in-out_infinite] rounded-full bg-acid" />}
        </div>
        <span className="font-mono text-[11px] text-white/40">{known ? `${formatMB(Math.min(loaded, total))} / ${formatMB(total)} MB` : loaded > 0 ? `${formatMB(loaded)} MB` : '\u00a0'}</span>
      </div>
    </div>
  )
}

const fileNameOf = (src) => {
  const name = src.split('?')[0].split('/').at(-1)
  try { return decodeURIComponent(name) } catch { return name }
}

export default function ThreeViewer({ src, name, size }) {
  const containerRef = useRef(null)
  const runtimeRef = useRef(null)
  const [ready, setReady] = useState(false)
  const [showSpinner, setShowSpinner] = useState(true)
  const [progress, setProgress] = useState({ loaded: 0, total: 0 })
  const [error, setError] = useState(false)
  const [initializationError, setInitializationError] = useState(false)
  const [retry, setRetry] = useState(0)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [environment, setEnvironment] = useState('Studio')
  const [strength, setStrength] = useState(1)
  const [look, setLook] = useState(() => ({ ...STUDIO_DEFAULTS }))
  const [rotation, setRotation] = useState(0)
  const [autoRotate, setAutoRotate] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    const handler = () => setIsFullscreen(document.fullscreenElement === containerRef.current)
    document.addEventListener('fullscreenchange', handler)
    return () => document.removeEventListener('fullscreenchange', handler)
  }, [])

  useEffect(() => {
    let disposed = false
    let runtime
    modulesPromise.then((modules) => {
      if (disposed) return
      runtime = createGalleryRuntime(containerRef.current, modules, {
        onLoading: (loading, failed) => { setShowSpinner(loading); setError(failed) },
        onProgress: setProgress,
        onRotation: setRotation,
      }, { strength: 1, rotation: 0, autoRotate: false, look: STUDIO_DEFAULTS })
      runtimeRef.current = runtime
      setReady(true)
    }).catch(() => {
      if (!disposed) { setShowSpinner(false); setInitializationError(true) }
    })
    return () => {
      disposed = true
      runtime?.dispose()
      runtimeRef.current = null
    }
  }, [])

  useEffect(() => {
    if (ready) runtimeRef.current?.loadModel(src, size)
  }, [src, size, ready, retry])
  useEffect(() => {
    if (ready) runtimeRef.current?.loadEnvironment(environmentUrl(environment))
  }, [environment, ready])
  useEffect(() => {
    if (runtimeRef.current) runtimeRef.current.scene.environmentIntensity = strength
  }, [strength, ready])
  useEffect(() => {
    const runtime = runtimeRef.current
    if (runtime) {
      runtime.environmentRotation = runtime.THREE.MathUtils.degToRad(rotation)
      runtime.scene.environmentRotation.y = runtime.environmentRotation
    }
  }, [rotation, ready])
  useEffect(() => {
    if (runtimeRef.current) runtimeRef.current.autoRotate = autoRotate
  }, [autoRotate, ready])
  useEffect(() => {
    runtimeRef.current?.setLook(look)
  }, [look, ready])

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen()
      else await containerRef.current?.requestFullscreen()
    } catch { setMessage('Fullscreen is not available in this browser.') }
  }
  const buttonClass = 'rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-xs text-white transition hover:border-acid/60 disabled:cursor-not-allowed disabled:opacity-40'

  return (
    <div ref={containerRef} className="three-viewer relative h-[62vh] min-h-[520px] w-full overflow-hidden bg-[radial-gradient(circle_at_50%_48%,rgba(89,91,76,.34),transparent_35%),linear-gradient(145deg,#171914,#0b0c0a)] lg:h-full lg:min-h-0" aria-label={`${name} 3D model`}>
      <button type="button" onClick={toggleFullscreen} className="absolute right-5 top-5 z-10 grid h-10 w-10 place-items-center rounded-full border border-white/10 bg-black/30 text-white/60 backdrop-blur transition hover:border-acid/50 hover:text-acid" aria-label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}>
        <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-2"><path d={isFullscreen ? 'M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5' : 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5'} /></svg>
      </button>
      <button type="button" onClick={() => setSettingsOpen((value) => !value)} className="absolute right-5 top-[68px] z-10 grid h-10 w-10 place-items-center rounded-full border border-white/10 bg-black/30 text-white/60 backdrop-blur transition hover:border-acid/50 hover:text-acid" aria-label="Environment settings">☼</button>
      <a href={src} download={fileNameOf(src)} className="absolute right-5 top-[116px] z-10 grid h-10 w-10 place-items-center rounded-full border border-white/10 bg-black/30 text-white/60 backdrop-blur transition hover:border-acid/50 hover:text-acid" aria-label={`Download ${name} (GLB)`} title="Download this model (GLB)">
        <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-2" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14" /></svg>
      </a>
      {message && <p className="absolute right-5 top-[164px] z-10 max-w-[240px] rounded-lg bg-black/60 px-3 py-2 text-xs text-white/70" role="status">{message}</p>}
      <EnvironmentPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} environment={environment} setEnvironment={setEnvironment} strength={strength} setStrength={setStrength} rotation={rotation} setRotation={setRotation} autoRotate={autoRotate} setAutoRotate={setAutoRotate} look={look} setLook={setLook} />
      {showSpinner && <LoadingOverlay progress={progress} />}
      {(error || initializationError) && <div className="pointer-events-none absolute inset-0 z-[5] grid place-items-center text-sm text-white/70"><div className="pointer-events-auto rounded-xl bg-black/80 p-5 text-center" role="alert"><p>{initializationError ? 'Could not start the 3D viewer. Check WebGL and your CDN connection.' : 'Failed to load model'}</p><button type="button" className={`${buttonClass} mt-3`} onClick={() => initializationError ? window.location.reload() : setRetry((value) => value + 1)}>{initializationError ? 'Reload page' : 'Retry model'}</button></div></div>}
    </div>
  )
}
