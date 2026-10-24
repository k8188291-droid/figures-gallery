import { useEffect, useMemo, useState } from 'react'
import ThreeViewer from './ThreeViewer'

const modelHash = (name) => encodeURIComponent(name.replace(/\s+/g, '_'))
const modelFromHash = (models) => {
  const hash = window.location.hash.slice(1)
  const value = decodeURIComponent(hash)
  return models.find((model) => modelHash(model.name) === hash || model.name === value || model.id === value)
}

const resolveAsset = (path) => path ? `${import.meta.env.BASE_URL}${path}` : undefined
const displayName = (name) => name.replace(/[._-]+/g, ' ').trim()

function EmptyViewer() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-8 text-center text-stone-400">
      <div className="grid h-20 w-20 place-items-center rounded-full border border-stone-700 text-4xl">◇</div>
      <div>
        <p className="text-lg font-medium text-stone-200">No models found</p>
        <p className="mt-2 max-w-sm text-sm leading-6">Upload GLB files to the model bucket (or the local models folder during development), then reload.</p>
      </div>
    </div>
  )
}

function App({ models }) {
  const initialModel = useMemo(() => modelFromHash(models) ?? models[0], [models])
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 1280)
  const [previewTextVisible, setPreviewTextVisible] = useState(true)
  const folders = useMemo(() => [...new Set(models.map((model) => model.folder))], [models])
  const [folder, setFolder] = useState(initialModel?.folder ?? folders[0] ?? '')
  const visibleModels = useMemo(
    () => models.filter((model) => model.folder === folder),
    [folder, models],
  )
  const [selectedId, setSelectedId] = useState(initialModel?.id)
  const selected = models.find((model) => model.id === selectedId) ?? visibleModels[0]

  useEffect(() => {
    if (!visibleModels.some((model) => model.id === selectedId)) {
      setSelectedId(visibleModels[0]?.id)
    }
  }, [folder, selectedId, visibleModels])

  useEffect(() => {
    const selectFromHash = () => {
      const model = modelFromHash(models)
      if (!model) return
      setFolder(model.folder)
      setSelectedId(model.id)
    }
    window.addEventListener('hashchange', selectFromHash)
    return () => window.removeEventListener('hashchange', selectFromHash)
  }, [models])

  const selectModel = (model) => {
    setSelectedId(model.id)
    window.location.hash = modelHash(model.name)
  }

  const navigateModel = (direction) => {
    if (visibleModels.length < 2) return
    const index = visibleModels.findIndex((model) => model.id === selected?.id)
    selectModel(visibleModels[(index + direction + visibleModels.length) % visibleModels.length])
  }

  return (
    <main className="min-h-screen bg-paper p-3 text-ink sm:p-5 lg:h-screen lg:overflow-hidden lg:p-6">
      <div className={`mx-auto grid min-h-[calc(100vh-1.5rem)] max-w-[1800px] overflow-hidden rounded-[1.75rem] border border-black/10 bg-white shadow-[0_28px_80px_rgba(20,20,15,.14)] transition-[grid-template-columns] duration-300 lg:h-[calc(100vh-3rem)] lg:min-h-0 ${sidebarOpen ? 'lg:grid-cols-[minmax(0,1fr)_420px]' : 'lg:grid-cols-[minmax(0,1fr)_64px]'}`}>
        <section className="relative min-h-[62vh] overflow-hidden bg-ink lg:min-h-0">
          <header className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-start justify-between p-6 text-white sm:p-8">
            <div>
              <button type="button" onClick={() => setPreviewTextVisible((value) => !value)} className="pointer-events-auto flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[.3em] text-acid" aria-label={previewTextVisible ? 'Hide preview text' : 'Show preview text'}>
                <span className="h-2 w-2 shrink-0 rounded-full bg-acid shadow-[0_0_16px_#d9ff43]" />
                {previewTextVisible && <span>Digital collection</span>}
              </button>
              {previewTextVisible && <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">3D MODEL<br />ARCHIVE</h1>}
            </div>
          </header>

          {selected ? (
            <ThreeViewer
              src={resolveAsset(selected.path)}
              name={displayName(selected.name)}
              onNavigate={navigateModel}
              canNavigate={visibleModels.length > 1}
            />
          ) : <EmptyViewer />}

          {previewTextVisible && <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between bg-gradient-to-t from-black/80 via-black/20 to-transparent p-6 pt-24 text-white sm:p-8 sm:pt-32">
            <div>
              <p className="text-xs uppercase tracking-[.24em] text-white/45">Selected object</p>
              <h2 className="mt-2 text-2xl font-medium sm:text-4xl">{selected ? displayName(selected.name) : 'No model'}</h2>
              {selected && <p className="mt-2 text-sm text-white/45">{selected.folder} · GLB</p>}
            </div>
            <p className="hidden max-w-[180px] text-right text-xs leading-5 text-white/50 sm:block">Drag to rotate · Scroll to zoom<br />Double-click to reset</p>
          </div>}
        </section>

        <aside className="relative flex min-h-[520px] flex-col bg-[#12130f] lg:min-h-0">
          <button
            type="button"
            onClick={() => setSidebarOpen((value) => !value)}
            className="absolute -left-4 top-1/2 z-30 hidden h-10 w-10 -translate-y-1/2 place-items-center rounded-full border border-white/10 bg-[#1d1f19] text-sm text-white shadow-xl transition hover:border-acid/50 hover:text-acid lg:grid"
            aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
          >
            {sidebarOpen ? '›' : '‹'}
          </button>
          {!sidebarOpen && <div className="hidden h-full flex-col items-center justify-center gap-5 lg:flex"><span className="text-acid">{String(models.length).padStart(2, '0')}</span><span className="[writing-mode:vertical-rl] text-[10px] font-semibold uppercase tracking-[.3em] text-white/35">Model Library</span></div>}
          <div className={`min-h-0 flex-1 flex-col ${sidebarOpen ? 'flex' : 'flex lg:hidden'}`}>
          <div className="border-b border-white/10 p-6 sm:p-8">
            <div className="flex items-end justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[.25em] text-white/35">The collection</p>
                <h2 className="mt-2 text-3xl font-semibold tracking-tight">Model Library</h2>
              </div>
              <span className="font-mono text-sm text-white/35">{String(visibleModels.length).padStart(2, '0')}</span>
            </div>
            <label className="mt-7 block text-xs font-medium text-white/45" htmlFor="folder">Select folder</label>
            <div className="relative mt-2">
              <select
                id="folder"
                value={folder}
                onChange={(event) => setFolder(event.target.value)}
                className="w-full appearance-none rounded-xl border border-white/10 bg-[#1d1f19] px-4 py-3.5 pr-11 text-sm font-medium text-white outline-none transition focus:border-acid/70 focus:ring-2 focus:ring-acid/10"
              >
                {folders.map((item) => <option key={item}>{item}</option>)}
              </select>
              <span className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-xs text-white/50">▼</span>
            </div>
          </div>

          <div className="model-list flex-1 overflow-y-auto p-3 sm:p-4">
            {visibleModels.map((model, index) => {
              const isSelected = model.id === selected?.id
              return (
                <button
                  key={model.id}
                  type="button"
                  onClick={() => selectModel(model)}
                  className={`group grid w-full grid-cols-[76px_1fr_auto] items-center gap-4 rounded-2xl p-3 text-left transition ${isSelected ? 'bg-acid text-ink shadow-lg shadow-black/20' : 'text-stone-100 hover:bg-white/[.06]'}`}
                >
                  <div className={`grid aspect-square place-items-center overflow-hidden rounded-xl ${isSelected ? 'bg-black/10' : 'bg-white/[.06]'}`}>
                    {model.thumbnail ? (
                      <img className="h-full w-full object-cover transition duration-500 group-hover:scale-105" src={resolveAsset(model.thumbnail)} alt="" />
                    ) : <span className="text-2xl opacity-40">◇</span>}
                  </div>
                  <div className="min-w-0">
                    <p className={`truncate text-[10px] font-semibold uppercase tracking-[.2em] ${isSelected ? 'text-black/50' : 'text-white/30'}`}>{model.folder}</p>
                    <p className="mt-1 truncate text-base font-semibold">{displayName(model.name)}</p>
                    <p className={`mt-1 text-xs ${isSelected ? 'text-black/45' : 'text-white/30'}`}>Interactive 3D</p>
                  </div>
                  <span className={`mr-2 text-sm transition-transform group-hover:translate-x-1 ${isSelected ? 'text-black/60' : 'text-white/25'}`}>↗</span>
                </button>
              )
            })}
            {!visibleModels.length && <p className="p-8 text-center text-sm text-white/35">No GLB models in this folder.</p>}
          </div>

          <div className="border-t border-white/10 px-6 py-4 sm:px-8">
            <a
              href="https://u.pcloud.link/publink/show?code=kZ0IdA5Z7ImlQeo5aLfgIHHO5rVeB7iu0nJX"
              target="_blank"
              rel="noreferrer"
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-acid px-4 py-3 text-sm font-bold text-ink transition hover:brightness-110"
            >
              Get Models <span aria-hidden="true">↗</span>
            </a>
          </div>

          <footer className="flex items-center justify-between border-t border-white/10 px-6 py-4 text-[10px] font-medium uppercase tracking-[.2em] text-white/30 sm:px-8">
            <span>WebGL gallery</span><span>© {new Date().getFullYear()}</span>
          </footer>
          </div>
        </aside>
      </div>
    </main>
  )
}

export default App
