import { createVRStage } from './vrStage'

export function disposeObject(root) {
  const resources = new Set()
  const images = new Set()
  root.traverse((child) => {
    if (child.geometry) resources.add(child.geometry)
    const materials = child.material ? (Array.isArray(child.material) ? child.material : [child.material]) : []
    materials.forEach((material) => {
      resources.add(material)
      Object.values(material).forEach((value) => {
        if (value?.isTexture) {
          resources.add(value)
          if (value.source?.data?.close) images.add(value.source.data)
        }
      })
    })
  })
  resources.forEach((resource) => resource.dispose())
  images.forEach((image) => image.close())
}

export function createGalleryRuntime(container, modules, callbacks, settings) {
  const [THREE, { GLTFLoader }, { OrbitControls }, { MeshoptDecoder }] = modules
  const scene = new THREE.Scene()
  scene.environmentIntensity = settings.strength
  const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 10000)
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
  renderer.xr.enabled = true
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.1
  Object.assign(renderer.domElement.style, { position: 'absolute', inset: '0', display: 'block', width: '100%', height: '100%' })
  container.appendChild(renderer.domElement)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.07
  controls.zoomToCursor = false
  scene.add(new THREE.HemisphereLight(0xffffff, 0x20241b, 1.2))
  const keyLight = new THREE.DirectionalLight(0xffffff, 2.4)
  keyLight.position.set(4, 6, 8)
  scene.add(keyLight)
  const pmrem = new THREE.PMREMGenerator(renderer)
  pmrem.compileEquirectangularShader()
  const loader = new GLTFLoader()
  loader.setMeshoptDecoder(MeshoptDecoder)
  let disposed = false
  let loadVersion = 0
  let environmentVersion = 0
  let environmentTarget
  let model
  let modelName = ''
  const modelSize = new THREE.Vector3()
  let radius = 1
  let preview = false
  let inVR = false
  let activeSession = null
  let entering = false
  let targetZoomDistance = null
  let lastTime = performance.now()
  let lastRotationUiUpdate = 0
  let pointerStart = null
  const touchPointers = new Set()
  const offset = new THREE.Vector3()
  const vr = createVRStage(THREE, renderer, scene, { onNavigate: callbacks.onNavigate, onExit: exitVR, onControllerStatus: callbacks.onControllerStatus })

  function resize() {
    if (renderer.xr.isPresenting || disposed) return
    const { clientWidth: width, clientHeight: height } = container
    if (!width || !height) return
    renderer.setSize(width, height, false)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
  }
  const resizeObserver = new ResizeObserver(resize)
  resizeObserver.observe(container)
  resize()

  function resetCamera() {
    if (inVR) { vr.reset(); return }
    camera.fov = 35
    camera.zoom = 1
    camera.up.set(0, 1, 0)
    if (preview) {
      camera.position.set(1.4, 1.8, 1.5)
      controls.target.set(0, 0.95, -1.1)
      camera.near = 0.01
      camera.far = 50
      controls.minDistance = 0.3
      controls.maxDistance = 12
    } else {
      const distance = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2))
      camera.position.set(distance * 1.05, radius * 0.12, 0)
      controls.target.set(0, 0, 0)
      camera.near = Math.max(radius / 100, 0.001)
      camera.far = distance * 25
      controls.minDistance = distance * 0.1
      controls.maxDistance = distance * 10
    }
    camera.updateProjectionMatrix()
    targetZoomDistance = camera.position.distanceTo(controls.target)
    // Flush any OrbitControls momentum before restoring the desktop view.
    controls.enableDamping = false
    controls.update()
    controls.enableDamping = true
    resize()
  }
  function applyMode() {
    const roomVisible = preview || inVR
    vr.setModel(null)
    vr.setVisible(roomVisible)
    scene.background = roomVisible ? new THREE.Color(0x111a21) : null
    if (model) {
      if (roomVisible) vr.setModel(model, modelSize, modelName)
      else scene.add(model)
    }
    if (!inVR) { vr.previewPlacement(); resetCamera() }
  }
  function sessionEnded() {
    if (disposed) return
    activeSession?.removeEventListener('visibilitychange', visibilityChanged)
    activeSession = null
    inVR = false
    entering = false
    controls.enabled = true
    touchPointers.clear()
    applyMode()
    callbacks.onVR(false)
  }
  function visibilityChanged() {
    vr.setSessionVisibility(activeSession?.visibilityState)
  }
  renderer.xr.addEventListener('sessionend', sessionEnded)
  async function exitVR() {
    if (activeSession) {
      try { await activeSession.end() } catch { callbacks.onMessage('Unable to exit VR. Use your headset’s system menu.') }
    } else if (!inVR) {
      preview = false
      applyMode()
      callbacks.onPreview(false)
    }
  }
  async function enterVR(quality) {
    if (entering || inVR || disposed) return
    entering = true
    callbacks.onMessage('Connecting to headset…')
    let session
    try {
      renderer.xr.setFramebufferScaleFactor(Number(quality))
      session = await navigator.xr.requestSession('immersive-vr', { optionalFeatures: ['local-floor'] })
      if (disposed) { await session.end(); return }
      // Attach Three.js input listeners immediately after requestSession resolves.
      // Awaiting a separate reference-space request here can miss initial input events.
      // If the runtime cannot report granted features, use the universally available local space.
      const floorTracked = Array.from(session.enabledFeatures || []).includes('local-floor')
      renderer.xr.setReferenceSpaceType(floorTracked ? 'local-floor' : 'local')
      activeSession = session
      session.addEventListener('visibilitychange', visibilityChanged)
      visibilityChanged()
      inVR = true
      controls.enabled = false
      camera.position.set(0, 0, 0)
      camera.quaternion.identity()
      camera.near = 0.01
      camera.far = 50
      camera.updateProjectionMatrix()
      targetZoomDistance = null
      applyMode()
      vr.preparePlacement(floorTracked)
      await renderer.xr.setSession(session)
      if (disposed) { await session.end(); return }
      callbacks.onVR(true)
      callbacks.onMessage('VR active — use the floating panel or your headset menu to exit.')
    } catch (error) {
      if (session) await session.end().catch(() => {})
      if (!disposed) {
        sessionEnded()
        callbacks.onMessage(error.name === 'NotAllowedError'
          ? 'VR access was declined. Allow it in the browser and try again.'
          : 'Could not start VR. Check your headset connection and active OpenXR runtime, then retry.')
      }
    } finally { entering = false }
  }
  function loadModel(src, name, canNavigate) {
    const version = ++loadVersion
    modelName = name
    vr.setModel(null)
    if (model) { model.removeFromParent(); disposeObject(model); model = null }
    vr.setStatus(`Loading: ${name}`, canNavigate)
    callbacks.onLoading(true, false)
    loader.load(src, (gltf) => {
      if (disposed || version !== loadVersion) { disposeObject(gltf.scene); return }
      model = gltf.scene
      const box = new THREE.Box3().setFromObject(model)
      model.position.sub(box.getCenter(new THREE.Vector3()))
      box.setFromObject(model)
      box.getSize(modelSize)
      radius = Math.max(box.getBoundingSphere(new THREE.Sphere()).radius, 0.01)
      if (preview || inVR) vr.setModel(model, modelSize, modelName)
      else scene.add(model)
      if (!inVR && !preview) resetCamera()
      vr.setStatus('', canNavigate)
      callbacks.onLoading(false, false)
    }, undefined, () => {
      if (disposed || version !== loadVersion) return
      vr.setStatus('Model failed to load — select another or retry on desktop', canNavigate)
      callbacks.onLoading(false, true)
    })
  }
  function loadEnvironment(url) {
    const version = ++environmentVersion
    new THREE.TextureLoader().load(url, (texture) => {
      if (disposed || version !== environmentVersion) { texture.dispose(); return }
      texture.colorSpace = THREE.SRGBColorSpace
      texture.mapping = THREE.EquirectangularReflectionMapping
      const next = pmrem.fromEquirectangular(texture)
      texture.dispose()
      scene.environment = next.texture
      environmentTarget?.dispose()
      environmentTarget = next
    }, undefined, () => {})
  }
  const handleDoubleClick = (event) => { event.preventDefault(); resetCamera() }
  const handleWheel = (event) => {
    event.preventDefault()
    event.stopImmediatePropagation()
    if (inVR || targetZoomDistance === null) return
    targetZoomDistance = THREE.MathUtils.clamp(targetZoomDistance * Math.exp(event.deltaY * 0.001), controls.minDistance, controls.maxDistance)
  }
  const handlePointerDown = (event) => {
    pointerStart = { x: event.clientX, y: event.clientY }
    if (event.pointerType === 'touch') touchPointers.add(event.pointerId)
  }
  const handlePointerUp = (event) => {
    if (preview && pointerStart && Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) < 5) vr.click(event, camera)
    pointerStart = null
    touchPointers.delete(event.pointerId)
  }
  const handlePointerCancel = (event) => { pointerStart = null; touchPointers.delete(event.pointerId) }
  renderer.domElement.addEventListener('dblclick', handleDoubleClick)
  renderer.domElement.addEventListener('wheel', handleWheel, { passive: false, capture: true })
  renderer.domElement.addEventListener('pointerdown', handlePointerDown)
  renderer.domElement.addEventListener('pointerup', handlePointerUp)
  renderer.domElement.addEventListener('pointercancel', handlePointerCancel)
  const runtime = {
    scene, THREE, loadModel, loadEnvironment, enterVR, exitVR,
    autoRotate: settings.autoRotate,
    environmentRotation: THREE.MathUtils.degToRad(settings.rotation),
    setPreview(value) {
      if (inVR || entering) return
      preview = value
      applyMode()
      callbacks.onPreview(preview)
    },
    dispose() {
      disposed = true
      renderer.setAnimationLoop(null)
      renderer.xr.removeEventListener('sessionend', sessionEnded)
      const session = activeSession
      session?.removeEventListener('visibilitychange', visibilityChanged)
      activeSession = null
      session?.end().catch(() => {})
      resizeObserver.disconnect()
      controls.dispose()
      vr.dispose()
      renderer.domElement.removeEventListener('dblclick', handleDoubleClick)
      renderer.domElement.removeEventListener('wheel', handleWheel, true)
      renderer.domElement.removeEventListener('pointerdown', handlePointerDown)
      renderer.domElement.removeEventListener('pointerup', handlePointerUp)
      renderer.domElement.removeEventListener('pointercancel', handlePointerCancel)
      disposeObject(scene)
      environmentTarget?.dispose()
      pmrem.dispose()
      renderer.dispose()
      renderer.domElement.remove()
    },
  }
  scene.environmentRotation.y = runtime.environmentRotation
  renderer.setAnimationLoop((time, frame) => {
    const delta = Math.max(0, Math.min((time - lastTime) / 1000, 0.05))
    lastTime = time
    if (runtime.autoRotate) {
      runtime.environmentRotation = (runtime.environmentRotation + delta * 0.25) % (Math.PI * 2)
      scene.environmentRotation.y = runtime.environmentRotation
      if (time - lastRotationUiUpdate >= 80) {
        lastRotationUiUpdate = time
        callbacks.onRotation(Math.round(THREE.MathUtils.radToDeg(runtime.environmentRotation)) % 360)
      }
    }
    if (!inVR) {
      if (targetZoomDistance !== null && touchPointers.size < 2) {
        offset.copy(camera.position).sub(controls.target)
        const distance = offset.length()
        const damped = THREE.MathUtils.damp(distance, targetZoomDistance, 9, delta)
        if (distance > 0) camera.position.copy(controls.target).add(offset.multiplyScalar(damped / distance))
      }
      controls.update()
      if (touchPointers.size >= 2) targetZoomDistance = camera.position.distanceTo(controls.target)
    }
    vr.update(frame, time)
    renderer.render(scene, camera)
  })
  return runtime
}
