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
    <div className={`absolute right-4 top-[116px] z-20 max-h-[calc(100%-132px)] w-[260px] overflow-y-auto rounded-2xl border border-white/10 bg-[#17181b]/95 p-4 text-white shadow-2xl backdrop-blur-xl transition ${open ? 'translate-x-0 opacity-100' : 'pointer-events-none translate-x-3 opacity-0'}`}>
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

export default function ThreeViewer({ src, name, onNavigate, canNavigate }) {
  const containerRef = useRef(null)
  const runtimeRef = useRef(null)
  const propsRef = useRef({ onNavigate })
  propsRef.current = { onNavigate }
  const [ready, setReady] = useState(false)
  const [showSpinner, setShowSpinner] = useState(true)
  const [error, setError] = useState(false)
  const [initializationError, setInitializationError] = useState(false)
  const [retry, setRetry] = useState(0)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [vrOpen, setVROpen] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [environment, setEnvironment] = useState('Studio')
  const [strength, setStrength] = useState(1)
  const [look, setLook] = useState(() => ({ ...STUDIO_DEFAULTS }))
  const [rotation, setRotation] = useState(0)
  const [autoRotate, setAutoRotate] = useState(false)
  const [xrSupport, setXRSupport] = useState('checking')
  const [xrMessage, setXRMessage] = useState('')
  const [controllerStatus, setControllerStatus] = useState('')
  const [inVR, setInVR] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [preview, setPreview] = useState(false)
  const [quality, setQuality] = useState('0.8')

  useEffect(() => {
    let active = true
    const check = async () => {
      if (!window.isSecureContext) { if (active) setXRSupport('insecure'); return }
      if (!navigator.xr) { if (active) setXRSupport('unavailable'); return }
      try {
        const supported = await navigator.xr.isSessionSupported('immersive-vr')
        if (active) setXRSupport(supported ? 'supported' : 'unavailable')
      } catch { if (active) setXRSupport('unavailable') }
    }
    check()
    navigator.xr?.addEventListener('devicechange', check)
    window.addEventListener('focus', check)
    return () => {
      active = false
      navigator.xr?.removeEventListener('devicechange', check)
      window.removeEventListener('focus', check)
    }
  }, [vrOpen])

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
        onNavigate: (direction) => propsRef.current.onNavigate?.(direction),
        onLoading: (loading, failed) => { setShowSpinner(loading); setError(failed) },
        onRotation: setRotation,
        onVR: setInVR,
        onPreview: setPreview,
        onMessage: setXRMessage,
        onControllerStatus: setControllerStatus,
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
    if (ready) runtimeRef.current?.loadModel(src, name, canNavigate)
  }, [src, name, canNavigate, ready, retry])
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
    } catch { setXRMessage('Fullscreen is not available in this browser.') }
  }
  const enterVR = async () => {
    setConnecting(true)
    try { await runtimeRef.current?.enterVR(quality) } finally { setConnecting(false) }
  }
  const supportMessage = {
    checking: 'Checking for a VR headset…',
    supported: 'Headset detected. Ready for PC VR.',
    insecure: 'Open this page using HTTPS or localhost to use VR.',
    unavailable: 'No VR headset detected. Connect your headset and check the active OpenXR runtime. Reopen this panel to check again.',
  }[xrSupport]
  const buttonClass = 'rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-xs text-white transition hover:border-acid/60 disabled:cursor-not-allowed disabled:opacity-40'

  return (
    <div ref={containerRef} className="three-viewer relative h-[62vh] min-h-[520px] w-full overflow-hidden bg-[radial-gradient(circle_at_50%_48%,rgba(89,91,76,.34),transparent_35%),linear-gradient(145deg,#171914,#0b0c0a)] lg:h-full lg:min-h-0" aria-label={`${name} 3D model`}>
      <button type="button" onClick={toggleFullscreen} className="absolute right-5 top-5 z-10 grid h-10 w-10 place-items-center rounded-full border border-white/10 bg-black/30 text-white/60 backdrop-blur transition hover:border-acid/50 hover:text-acid" aria-label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}>
        <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-2"><path d={isFullscreen ? 'M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5' : 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5'} /></svg>
      </button>
      <button type="button" onClick={() => { setSettingsOpen((value) => !value); setVROpen(false) }} className="absolute right-5 top-[68px] z-10 grid h-10 w-10 place-items-center rounded-full border border-white/10 bg-black/30 text-white/60 backdrop-blur transition hover:border-acid/50 hover:text-acid" aria-label="Environment settings">☼</button>
      <button type="button" onClick={() => { setVROpen((value) => !value); setSettingsOpen(false) }} aria-expanded={vrOpen} aria-controls="vr-panel" className="absolute right-5 top-[116px] z-10 flex h-10 items-center gap-2 rounded-full border border-acid/40 bg-[#171e18]/90 px-4 text-xs font-semibold text-acid shadow-lg backdrop-blur transition hover:bg-acid hover:text-ink">
        <svg viewBox="0 0 24 24" className="h-5 w-5 fill-none stroke-current stroke-[1.5]" aria-hidden="true"><path d="M4 7h16l2 10h-6l-4-3-4 3H2Z" /><circle cx="7.5" cy="11" r="1.5" /><circle cx="16.5" cy="11" r="1.5" /></svg>
        {inVR ? 'VR active' : 'VR studio'}
      </button>
      {vrOpen && <div id="vr-panel" className="absolute right-5 top-[164px] z-20 w-[300px] max-w-[calc(100%-2.5rem)] rounded-2xl border border-white/15 bg-[#171c20]/95 p-4 text-white shadow-2xl backdrop-blur-xl">
        <div className="flex items-center justify-between"><h3 className="text-sm font-semibold">Your virtual display desk</h3><button type="button" onClick={() => setVROpen(false)} aria-label="Close VR settings" className="px-2 text-lg text-white/50">×</button></div>
        <p className="mt-2 text-xs leading-5 text-white/55" role="status">{supportMessage}</p>
        <label className="mt-3 block text-xs text-white/60" htmlFor="vr-quality">VR resolution</label>
        <select id="vr-quality" value={quality} onChange={(event) => setQuality(event.target.value)} disabled={inVR || connecting} className="mt-1 w-full rounded-lg border border-white/15 bg-[#222b30] px-3 py-2 text-xs disabled:opacity-50">
          <option value="0.6">Performance · 60%</option><option value="0.8">Balanced · 80%</option><option value="1">Native · 100%</option>
        </select>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <button type="button" className={`${buttonClass} !bg-acid !text-ink`} disabled={!ready || connecting || (!inVR && xrSupport !== 'supported')} onClick={inVR ? () => runtimeRef.current?.exitVR() : enterVR}>{connecting ? 'Connecting…' : inVR ? 'Exit VR' : 'Enter VR'}</button>
          <button type="button" className={buttonClass} disabled={!ready || inVR || connecting} onClick={() => { runtimeRef.current?.setPreview(!preview); setVROpen(false) }}>{preview ? 'Back to model' : 'Preview desk'}</button>
        </div>
        <p className="mt-3 text-[11px] leading-5 text-white/45">Point + trigger to select. Hold trigger or grip on the model to pick it up. Use the desk buttons to resize and reset.</p>
        {xrMessage && <p className="mt-2 text-xs leading-5 text-acid" role="status">{xrMessage}</p>}
        {controllerStatus && <p className="mt-2 text-xs leading-5 text-white/75" role="status">{inVR ? '' : 'Last VR status: '}{controllerStatus}</p>}
      </div>}
      {preview && <button type="button" onClick={() => runtimeRef.current?.setPreview(false)} className="absolute bottom-5 right-5 z-10 rounded-full border border-acid/30 bg-[#171c20]/90 px-4 py-2 text-xs text-acid backdrop-blur">Desk preview · Back to model</button>}
      <EnvironmentPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} environment={environment} setEnvironment={setEnvironment} strength={strength} setStrength={setStrength} rotation={rotation} setRotation={setRotation} autoRotate={autoRotate} setAutoRotate={setAutoRotate} look={look} setLook={setLook} />
      {showSpinner && <div className="pointer-events-none absolute inset-0 z-[5] grid place-items-center bg-ink/65 backdrop-blur-sm" role="status" aria-label="Loading model"><div className="flex flex-col items-center gap-4"><span className="h-12 w-12 animate-spin rounded-full border-2 border-white/15 border-t-acid" /><span className="text-[10px] font-semibold uppercase tracking-[.28em] text-white/55">Loading model</span></div></div>}
      {(error || initializationError) && <div className="pointer-events-none absolute inset-0 z-[5] grid place-items-center text-sm text-white/70"><div className="pointer-events-auto rounded-xl bg-black/80 p-5 text-center" role="alert"><p>{initializationError ? 'Could not start the 3D viewer. Check WebGL and your CDN connection.' : 'Failed to load model'}</p><button type="button" className={`${buttonClass} mt-3`} onClick={() => initializationError ? window.location.reload() : setRetry((value) => value + 1)}>{initializationError ? 'Reload page' : 'Retry model'}</button></div></div>}
    </div>
  )
}
