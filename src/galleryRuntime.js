import { STUDIO_DEFAULTS, applyStudioLook, createNeutralEnvironment } from './studioLook'

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
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.outputColorSpace = THREE.SRGBColorSpace
  Object.assign(renderer.domElement.style, { position: 'absolute', inset: '0', display: 'block', width: '100%', height: '100%' })
  container.appendChild(renderer.domElement)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.07
  controls.zoomToCursor = false
  // Legacy fill lights. The studio look (model-viewer parity) is IBL only, so
  // they stay hidden unless `fillLights` is turned on.
  const hemiLight = new THREE.HemisphereLight(0xffffff, 0x20241b, 1.2)
  const keyLight = new THREE.DirectionalLight(0xffffff, 2.4)
  keyLight.position.set(4, 6, 8)
  scene.add(hemiLight, keyLight)
  const pmrem = new THREE.PMREMGenerator(renderer)
  pmrem.compileEquirectangularShader()
  const look = applyStudioLook(THREE, renderer, scene, { ...STUDIO_DEFAULTS, ...settings.look, lights: [hemiLight, keyLight] })
  let neutralTarget
  const loader = new GLTFLoader()
  loader.setMeshoptDecoder(MeshoptDecoder)
  let disposed = false
  let loadVersion = 0
  let environmentVersion = 0
  let environmentTarget
  let model
  let radius = 1
  let targetZoomDistance = null
  let lastTime = performance.now()
  let lastRotationUiUpdate = 0
  const touchPointers = new Set()
  const offset = new THREE.Vector3()

  function resize() {
    if (disposed) return
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
    camera.fov = 35
    camera.zoom = 1
    camera.up.set(0, 1, 0)
    const distance = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2))
    camera.position.set(distance * 1.05, radius * 0.12, 0)
    controls.target.set(0, 0, 0)
    camera.near = Math.max(radius / 100, 0.001)
    camera.far = distance * 25
    controls.minDistance = distance * 0.1
    controls.maxDistance = distance * 10
    camera.updateProjectionMatrix()
    targetZoomDistance = camera.position.distanceTo(controls.target)
    // Flush any OrbitControls momentum before restoring the desktop view.
    controls.enableDamping = false
    controls.update()
    controls.enableDamping = true
    resize()
  }
  // `size` is the expected file size in bytes (from the model list). It is the
  // progress total when the response has no usable Content-Length.
  function loadModel(src, size) {
    const version = ++loadVersion
    look.shadow.fit(null)
    if (model) { model.removeFromParent(); disposeObject(model); model = null }
    callbacks.onLoading(true, false)
    callbacks.onProgress({ loaded: 0, total: size || 0 })
    loader.load(src, (gltf) => {
      if (disposed || version !== loadVersion) { disposeObject(gltf.scene); return }
      model = gltf.scene
      const box = new THREE.Box3().setFromObject(model)
      model.position.sub(box.getCenter(new THREE.Vector3()))
      box.setFromObject(model)
      radius = Math.max(box.getBoundingSphere(new THREE.Sphere()).radius, 0.01)
      scene.add(model)
      look.shadow.fit(model)
      resetCamera()
      callbacks.onLoading(false, false)
    }, (event) => {
      if (disposed || version !== loadVersion) return
      callbacks.onProgress({ loaded: event.loaded, total: event.lengthComputable ? event.total : size || 0 })
    }, () => {
      if (disposed || version !== loadVersion) return
      callbacks.onLoading(false, true)
    })
  }
  // `url` is a panorama image, or null for the procedural neutral studio.
  function loadEnvironment(url) {
    const version = ++environmentVersion
    if (!url) {
      neutralTarget ??= createNeutralEnvironment(THREE, renderer, pmrem)
      scene.environment = neutralTarget.texture
      environmentTarget?.dispose()
      environmentTarget = null
      look.update({ proceduralEnvironment: true })
      return
    }
    new THREE.TextureLoader().load(url, (texture) => {
      if (disposed || version !== environmentVersion) { texture.dispose(); return }
      texture.colorSpace = THREE.SRGBColorSpace
      texture.mapping = THREE.EquirectangularReflectionMapping
      const next = pmrem.fromEquirectangular(texture)
      texture.dispose()
      scene.environment = next.texture
      environmentTarget?.dispose()
      environmentTarget = next
      look.update({ proceduralEnvironment: false })
    }, undefined, () => {})
  }
  const handleDoubleClick = (event) => { event.preventDefault(); resetCamera() }
  const handleWheel = (event) => {
    event.preventDefault()
    event.stopImmediatePropagation()
    if (targetZoomDistance === null) return
    targetZoomDistance = THREE.MathUtils.clamp(targetZoomDistance * Math.exp(event.deltaY * 0.001), controls.minDistance, controls.maxDistance)
  }
  const handlePointerDown = (event) => {
    if (event.pointerType === 'touch') touchPointers.add(event.pointerId)
  }
  const handlePointerUp = (event) => { touchPointers.delete(event.pointerId) }
  renderer.domElement.addEventListener('dblclick', handleDoubleClick)
  renderer.domElement.addEventListener('wheel', handleWheel, { passive: false, capture: true })
  renderer.domElement.addEventListener('pointerdown', handlePointerDown)
  renderer.domElement.addEventListener('pointerup', handlePointerUp)
  renderer.domElement.addEventListener('pointercancel', handlePointerUp)
  const runtime = {
    scene, THREE, loadModel, loadEnvironment,
    /** Update tone mapping, exposure, shadow and fill-light options. */
    setLook(options) { look.update(options) },
    autoRotate: settings.autoRotate,
    environmentRotation: THREE.MathUtils.degToRad(settings.rotation),
    dispose() {
      disposed = true
      renderer.setAnimationLoop(null)
      resizeObserver.disconnect()
      controls.dispose()
      renderer.domElement.removeEventListener('dblclick', handleDoubleClick)
      renderer.domElement.removeEventListener('wheel', handleWheel, true)
      renderer.domElement.removeEventListener('pointerdown', handlePointerDown)
      renderer.domElement.removeEventListener('pointerup', handlePointerUp)
      renderer.domElement.removeEventListener('pointercancel', handlePointerUp)
      look.dispose()
      disposeObject(scene)
      environmentTarget?.dispose()
      neutralTarget?.dispose()
      pmrem.dispose()
      renderer.dispose()
      renderer.domElement.remove()
    },
  }
  scene.environmentRotation.y = runtime.environmentRotation
  renderer.setAnimationLoop((time) => {
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
    if (targetZoomDistance !== null && touchPointers.size < 2) {
      offset.copy(camera.position).sub(controls.target)
      const distance = offset.length()
      const damped = THREE.MathUtils.damp(distance, targetZoomDistance, 9, delta)
      if (distance > 0) camera.position.copy(controls.target).add(offset.multiplyScalar(damped / distance))
    }
    controls.update()
    if (touchPointers.size >= 2) targetZoomDistance = camera.position.distanceTo(controls.target)
    look.shadow.render(renderer, scene)
    renderer.render(scene, camera)
  })
  return runtime
}
