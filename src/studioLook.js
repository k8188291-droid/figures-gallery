// A pure three.js port of the <model-viewer> 3.5 "neutral" studio look:
// procedural neutral IBL, Khronos PBR Neutral tone mapping and a blurred
// contact shadow. Every function takes the THREE namespace as an argument so
// the module works with the CDN build that the gallery loads at runtime.
//
// Reference (@google/model-viewer@3.5.0, src/):
// - three-components/EnvironmentScene.ts  neutral room, boxes and area lights
// - three-components/TextureUtils.ts      256px cube capture + sigma 0.04 blur
// - three-components/Renderer.ts          exposure x 1.3 for neutral tone mapping
// - three-components/Shadow.ts            depth-from-below contact shadow
// - features/environment.ts               shadow intensity x 0.5, defaults

export const STUDIO_DEFAULTS = Object.freeze({
  toneMapping: 'neutral',
  exposure: 1.05,
  shadowIntensity: 0.7,
  shadowSoftness: 0.9,
  fillLights: false,
})

// model-viewer brightens its generated environments when the PBR Neutral
// tone mapper is active (Renderer.ts COMMERCE_EXPOSURE).
export const NEUTRAL_EXPOSURE_COMPENSATION = 1.3
// features/environment.ts BASE_OPACITY: shadow-intensity 1 means 50% opacity.
const SHADOW_BASE_OPACITY = 0.5
// Shadow.ts constants.
const LOG_MAX_RESOLUTION = 9
const LOG_MIN_RESOLUTION = 6
const DEFAULT_HARD_INTENSITY = 0.3
const TAP_WIDTH = 10
// TextureUtils.ts constants.
const GENERATED_SIGMA = 0.04
const MAX_SAMPLES = 20

const lerp = (a, b, t) => a + (b - a) * t

// EnvironmentScene.ts, `neutral` preset.
const NEUTRAL_ROOM = {
  topLight: { intensity: 400, position: [0.5, 14.0, 0.5] },
  room: { position: [0.0, 13.2, 0.0], scale: [31.5, 28.5, 31.5] },
  boxes: [
    { position: [-10.906, -1.0, 1.846], rotation: -0.195, scale: [2.328, 7.905, 4.651] },
    { position: [-5.607, -0.754, -0.758], rotation: 0.994, scale: [1.970, 1.534, 3.955] },
    { position: [6.167, -0.16, 7.803], rotation: 0.561, scale: [3.927, 6.285, 3.687] },
    { position: [-2.017, 0.018, 6.124], rotation: 0.333, scale: [2.002, 4.566, 2.064] },
    { position: [2.291, -0.756, -2.621], rotation: -0.286, scale: [1.546, 1.552, 1.496] },
    { position: [-2.193, -0.369, -5.547], rotation: 0.516, scale: [3.875, 3.487, 2.986] },
  ],
  lights: [
    { intensity: 80, position: [-14.0, 10.0, 8.0], scale: [0.1, 2.5, 2.5] },
    { intensity: 80, position: [-14.0, 14.0, -4.0], scale: [0.1, 2.5, 2.5] },
    { intensity: 23, position: [14.0, 12.0, 0.0], scale: [0.1, 5.0, 5.0] },
    { intensity: 16, position: [0.0, 9.0, 14.0], scale: [5.0, 5.0, 0.1] },
    { intensity: 80, position: [7.0, 8.0, -14.0], scale: [2.5, 2.5, 0.1] },
    { intensity: 80, position: [-7.0, 16.0, -14.0], scale: [2.5, 2.5, 0.1] },
    { intensity: 1, position: [0.0, 20.0, 0.0], scale: [0.1, 0.1, 0.1] },
  ],
}

export function createNeutralEnvironmentScene(THREE) {
  const scene = new THREE.Scene()
  scene.position.y = -3.5
  const geometry = new THREE.BoxGeometry()
  geometry.deleteAttribute('uv')
  const roomMaterial = new THREE.MeshStandardMaterial({ metalness: 0, side: THREE.BackSide })
  const boxMaterial = new THREE.MeshStandardMaterial({ metalness: 0 })
  const mainLight = new THREE.PointLight(0xffffff, NEUTRAL_ROOM.topLight.intensity, 28, 2)
  mainLight.position.set(...NEUTRAL_ROOM.topLight.position)
  scene.add(mainLight)
  const room = new THREE.Mesh(geometry, roomMaterial)
  room.position.set(...NEUTRAL_ROOM.room.position)
  room.scale.set(...NEUTRAL_ROOM.room.scale)
  scene.add(room)
  for (const box of NEUTRAL_ROOM.boxes) {
    const mesh = new THREE.Mesh(geometry, boxMaterial)
    mesh.position.set(...box.position)
    mesh.rotation.set(0, box.rotation, 0)
    mesh.scale.set(...box.scale)
    scene.add(mesh)
  }
  const materials = [roomMaterial, boxMaterial]
  for (const light of NEUTRAL_ROOM.lights) {
    const material = new THREE.MeshBasicMaterial()
    material.color.setScalar(light.intensity)
    materials.push(material)
    const mesh = new THREE.Mesh(geometry, material)
    mesh.position.set(...light.position)
    mesh.scale.set(...light.scale)
    scene.add(mesh)
  }
  scene.userData.dispose = () => { geometry.dispose(); materials.forEach((material) => material.dispose()) }
  return scene
}

function createSphericalBlurMaterial(THREE) {
  return new THREE.ShaderMaterial({
    name: 'SphericalGaussianBlur',
    defines: { n: MAX_SAMPLES },
    uniforms: {
      envMap: { value: null },
      samples: { value: 1 },
      weights: { value: new Float32Array(MAX_SAMPLES) },
      latitudinal: { value: false },
      dTheta: { value: 0 },
      poleAxis: { value: new THREE.Vector3(0, 1, 0) },
    },
    vertexShader: /* glsl */`
      varying vec3 vOutputDirection;
      void main() {
        vOutputDirection = vec3( position );
        gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
      }`,
    fragmentShader: /* glsl */`
      varying vec3 vOutputDirection;
      uniform samplerCube envMap;
      uniform int samples;
      uniform float weights[ n ];
      uniform bool latitudinal;
      uniform float dTheta;
      uniform vec3 poleAxis;
      vec3 getSample( float theta, vec3 axis ) {
        float cosTheta = cos( theta );
        vec3 sampleDirection = vOutputDirection * cosTheta
          + cross( axis, vOutputDirection ) * sin( theta )
          + axis * dot( axis, vOutputDirection ) * ( 1.0 - cosTheta );
        return vec3( textureCube( envMap, sampleDirection ) );
      }
      void main() {
        vec3 axis = latitudinal ? poleAxis : cross( poleAxis, vOutputDirection );
        if ( all( equal( axis, vec3( 0.0 ) ) ) ) axis = vec3( vOutputDirection.z, 0.0, - vOutputDirection.x );
        axis = normalize( axis );
        gl_FragColor = vec4( 0.0, 0.0, 0.0, 1.0 );
        gl_FragColor.rgb += weights[ 0 ] * getSample( 0.0, axis );
        for ( int i = 1; i < n; i++ ) {
          if ( i >= samples ) break;
          float theta = dTheta * float( i );
          gl_FragColor.rgb += weights[ i ] * getSample( -1.0 * theta, axis );
          gl_FragColor.rgb += weights[ i ] * getSample( theta, axis );
        }
      }`,
    side: THREE.BackSide,
    depthTest: false,
    depthWrite: false,
    blending: THREE.NoBlending,
  })
}

function halfBlur(THREE, renderer, blurScene, material, targetIn, targetOut, sigmaRadians, direction) {
  const radiansPerPixel = Math.PI / (2 * targetIn.width)
  const sigmaPixels = sigmaRadians / radiansPerPixel
  const samples = Math.min(1 + Math.floor(3 * sigmaPixels), MAX_SAMPLES)
  const weights = material.uniforms.weights.value
  let sum = 0
  for (let i = 0; i < MAX_SAMPLES; ++i) {
    const x = i / sigmaPixels
    weights[i] = Math.exp(-x * x / 2)
    if (i === 0) sum += weights[i]
    else if (i < samples) sum += 2 * weights[i]
  }
  for (let i = 0; i < MAX_SAMPLES; ++i) weights[i] /= sum
  material.uniforms.envMap.value = targetIn.texture
  material.uniforms.samples.value = samples
  material.uniforms.latitudinal.value = direction === 'latitudinal'
  material.uniforms.dTheta.value = radiansPerPixel
  new THREE.CubeCamera(0.1, 100, targetOut).update(renderer, blurScene)
}

/**
 * Renders model-viewer's neutral studio into a cube map, blurs it the same
 * way, and returns a PMREM render target ready for `scene.environment`.
 */
export function createNeutralEnvironment(THREE, renderer, pmrem) {
  const environmentScene = createNeutralEnvironmentScene(THREE)
  const cubeTarget = new THREE.WebGLCubeRenderTarget(256, {
    generateMipmaps: false,
    type: THREE.HalfFloatType,
    format: THREE.RGBAFormat,
    colorSpace: THREE.LinearSRGBColorSpace,
    depthBuffer: true,
  })
  const tempTarget = cubeTarget.clone()
  const blurMaterial = createSphericalBlurMaterial(THREE)
  const blurGeometry = new THREE.BoxGeometry()
  const blurScene = new THREE.Scene()
  blurScene.add(new THREE.Mesh(blurGeometry, blurMaterial))

  const { toneMapping, outputColorSpace } = renderer
  const xrEnabled = renderer.xr.enabled
  const previousTarget = renderer.getRenderTarget()
  renderer.toneMapping = THREE.NoToneMapping
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace
  renderer.xr.enabled = false
  new THREE.CubeCamera(0.1, 100, cubeTarget).update(renderer, environmentScene)
  halfBlur(THREE, renderer, blurScene, blurMaterial, cubeTarget, tempTarget, GENERATED_SIGMA, 'latitudinal')
  halfBlur(THREE, renderer, blurScene, blurMaterial, tempTarget, cubeTarget, GENERATED_SIGMA, 'longitudinal')
  const generator = pmrem ?? new THREE.PMREMGenerator(renderer)
  const target = generator.fromCubemap(cubeTarget.texture)
  renderer.toneMapping = toneMapping
  renderer.outputColorSpace = outputColorSpace
  renderer.xr.enabled = xrEnabled
  renderer.setRenderTarget(previousTarget)

  if (!pmrem) generator.dispose()
  environmentScene.userData.dispose()
  blurGeometry.dispose()
  blurMaterial.dispose()
  tempTarget.dispose()
  cubeTarget.dispose()
  target.texture.name = 'neutral'
  return target
}

/**
 * Applies tone mapping and exposure. `proceduralEnvironment` enables the same
 * x1.3 compensation that model-viewer uses with its generated environments.
 */
export function applyToneMapping(THREE, renderer, { toneMapping = STUDIO_DEFAULTS.toneMapping, exposure = STUDIO_DEFAULTS.exposure, proceduralEnvironment = false } = {}) {
  const mapping = { neutral: THREE.NeutralToneMapping, aces: THREE.ACESFilmicToneMapping, agx: THREE.AgXToneMapping }[toneMapping] ?? THREE.NeutralToneMapping
  renderer.toneMapping = mapping
  renderer.toneMappingExposure = exposure * (mapping === THREE.NeutralToneMapping && proceduralEnvironment ? NEUTRAL_EXPOSURE_COMPENSATION : 1)
}

const blurVertexShader = /* glsl */`
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = vec4( position.xy, 0.0, 1.0 ); }`
const blurFragmentShader = (axis) => /* glsl */`
  uniform sampler2D tDiffuse;
  uniform float step;
  varying vec2 vUv;
  void main() {
    vec2 d = ${axis === 'h' ? 'vec2( step, 0.0 )' : 'vec2( 0.0, step )'};
    vec4 sum = vec4( 0.0 );
    sum += texture2D( tDiffuse, vUv - 4.0 * d ) * 0.051;
    sum += texture2D( tDiffuse, vUv - 3.0 * d ) * 0.0918;
    sum += texture2D( tDiffuse, vUv - 2.0 * d ) * 0.12245;
    sum += texture2D( tDiffuse, vUv - 1.0 * d ) * 0.1531;
    sum += texture2D( tDiffuse, vUv ) * 0.1633;
    sum += texture2D( tDiffuse, vUv + 1.0 * d ) * 0.1531;
    sum += texture2D( tDiffuse, vUv + 2.0 * d ) * 0.12245;
    sum += texture2D( tDiffuse, vUv + 3.0 * d ) * 0.0918;
    sum += texture2D( tDiffuse, vUv + 4.0 * d ) * 0.051;
    gl_FragColor = sum;
  }`

/**
 * Soft contact shadow, ported from model-viewer's Shadow.ts: an orthographic
 * camera looks up from the bottom of the model's bounding box, renders depth
 * as black-to-transparent, blurs it, and shows it on a plane under the model.
 * It does not depend on light direction, so orbiting the camera or rotating
 * the environment never invalidates it. Call `fit(model)` after loading, and
 * `render(renderer, scene)` before each frame; it only re-renders when needed.
 */
export function createContactShadow(THREE, { intensity = STUDIO_DEFAULTS.shadowIntensity, softness = STUDIO_DEFAULTS.shadowSoftness } = {}) {
  const root = new THREE.Object3D()
  root.name = 'contact-shadow'
  const camera = new THREE.OrthographicCamera(-0.5, 0.5, 0.5, -0.5, 0, 1)
  camera.rotation.x = Math.PI / 2
  root.add(camera)
  const plane = new THREE.PlaneGeometry()
  const floorMaterial = new THREE.MeshBasicMaterial({ transparent: true, side: THREE.BackSide, depthWrite: false })
  const floor = new THREE.Mesh(plane, floorMaterial)
  floor.userData.noHit = true
  floor.renderOrder = -1
  camera.add(floor)

  const depthMaterial = new THREE.MeshDepthMaterial()
  depthMaterial.onBeforeCompile = (shader) => {
    shader.fragmentShader = shader.fragmentShader.replace(
      'gl_FragColor = vec4( vec3( 1.0 - fragCoordZ ), opacity );',
      'gl_FragColor = vec4( vec3( 0.0 ), ( 1.0 - fragCoordZ ) * opacity );')
  }
  const blurMaterial = (axis) => new THREE.ShaderMaterial({
    uniforms: { tDiffuse: { value: null }, step: { value: 0 } },
    vertexShader: blurVertexShader,
    fragmentShader: blurFragmentShader(axis),
    depthTest: false,
    depthWrite: false,
    blending: THREE.NoBlending,
  })
  const horizontal = blurMaterial('h')
  const vertical = blurMaterial('v')
  const blurQuad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), horizontal)
  blurQuad.frustumCulled = false
  const blurCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1)

  const box = new THREE.Box3()
  const size = new THREE.Vector3()
  const lastMatrix = new THREE.Matrix4()
  let target = null
  let renderTarget = null
  let renderTargetBlur = null
  let maxDimension = 0
  let needsUpdate = false
  const state = { intensity, softness }

  function setMapSize(maxMapSize) {
    const baseWidth = Math.max(1, Math.floor(size.x > size.z ? maxMapSize : maxMapSize * size.x / size.z))
    const baseHeight = Math.max(1, Math.floor(size.x > size.z ? maxMapSize * size.z / size.x : maxMapSize))
    const width = TAP_WIDTH + baseWidth
    const height = TAP_WIDTH + baseHeight
    if (renderTarget && (renderTarget.width !== width || renderTarget.height !== height)) {
      renderTarget.dispose(); renderTargetBlur.dispose()
      renderTarget = renderTargetBlur = null
    }
    if (!renderTarget) {
      renderTarget = new THREE.WebGLRenderTarget(width, height, { format: THREE.RGBAFormat })
      renderTargetBlur = new THREE.WebGLRenderTarget(width, height, { format: THREE.RGBAFormat })
      floorMaterial.map = renderTarget.texture
      floorMaterial.needsUpdate = true
    }
    // Pad the frustum so the blur radius is not clipped at the edges.
    camera.scale.set(size.x * (1 + TAP_WIDTH / baseWidth), size.z * (1 + TAP_WIDTH / baseHeight), 1)
    needsUpdate = true
  }

  function applyIntensity() {
    const visible = state.intensity > 0 && target !== null
    floor.visible = visible
    floorMaterial.opacity = state.intensity * SHADOW_BASE_OPACITY * lerp(DEFAULT_HARD_INTENSITY, 1, state.softness * state.softness)
  }

  function applySoftness() {
    if (!target) return
    const softness = Math.max(state.softness, 1e-3)
    setMapSize(Math.pow(2, LOG_MAX_RESOLUTION - softness * (LOG_MAX_RESOLUTION - LOG_MIN_RESOLUTION)))
    camera.near = 0
    camera.far = lerp(size.y, size.y / 2, softness)
    camera.updateProjectionMatrix()
    // The depth material's opacity scales depth into the clip range.
    depthMaterial.opacity = 1 / softness
    floor.position.z = 0.001 * maxDimension
    applyIntensity()
  }

  function render(renderer, scene) {
    if (!target || !floor.visible || !root.visible) return
    target.updateWorldMatrix(true, false)
    if (!lastMatrix.equals(target.matrixWorld)) needsUpdate = true
    if (!needsUpdate) return
    lastMatrix.copy(target.matrixWorld)
    needsUpdate = false

    // Only the target may contribute depth: hide every other top-level child.
    let branch = target
    while (branch.parent && branch.parent !== scene) branch = branch.parent
    const hidden = scene.children.filter((child) => child !== branch && child.visible)
    hidden.forEach((child) => { child.visible = false })
    const { background, overrideMaterial } = scene
    const clearAlpha = renderer.getClearAlpha()
    const xrEnabled = renderer.xr.enabled
    const previousTarget = renderer.getRenderTarget()
    scene.background = null
    scene.overrideMaterial = depthMaterial
    renderer.setClearAlpha(0)
    renderer.xr.enabled = false
    root.updateWorldMatrix(true, true)
    renderer.setRenderTarget(renderTarget)
    renderer.clear()
    renderer.render(scene, camera)
    scene.overrideMaterial = overrideMaterial
    scene.background = background
    hidden.forEach((child) => { child.visible = true })

    horizontal.uniforms.tDiffuse.value = renderTarget.texture
    horizontal.uniforms.step.value = 1 / renderTarget.width
    blurQuad.material = horizontal
    renderer.setRenderTarget(renderTargetBlur)
    renderer.render(blurQuad, blurCamera)
    vertical.uniforms.tDiffuse.value = renderTargetBlur.texture
    vertical.uniforms.step.value = 1 / renderTarget.height
    blurQuad.material = vertical
    renderer.setRenderTarget(renderTarget)
    renderer.render(blurQuad, blurCamera)

    renderer.setRenderTarget(previousTarget)
    renderer.xr.enabled = xrEnabled
    renderer.setClearAlpha(clearAlpha)
  }

  return {
    object: root,
    /** Size the shadow to `model`'s bounding box (in the shadow's parent space). */
    fit(model) {
      target = model
      if (!model) { applyIntensity(); return }
      root.updateWorldMatrix(true, false)
      box.setFromObject(model)
      if (root.parent) box.applyMatrix4(new THREE.Matrix4().copy(root.parent.matrixWorld).invert())
      box.getSize(size)
      maxDimension = Math.max(size.x, size.y, size.z, 1e-6)
      size.max(new THREE.Vector3(1e-6, 1e-6, 1e-6))
      box.getCenter(root.position)
      root.position.y = box.min.y
      applySoftness()
    },
    setIntensity(value) { state.intensity = value; applyIntensity() },
    setSoftness(value) { state.softness = THREE.MathUtils.clamp(value, 0, 1); applySoftness(); applyIntensity() },
    get intensity() { return state.intensity },
    get softness() { return state.softness },
    invalidate() { needsUpdate = true },
    render,
    dispose() {
      renderTarget?.dispose()
      renderTargetBlur?.dispose()
      depthMaterial.dispose()
      horizontal.dispose()
      vertical.dispose()
      blurQuad.geometry.dispose()
      floorMaterial.dispose()
      plane.dispose()
      root.removeFromParent()
    },
  }
}

/**
 * Convenience wrapper: tone mapping, optional legacy fill lights and the
 * contact shadow in one object. `fillLights` are the gallery's old
 * Hemisphere/Directional lights; model-viewer itself uses IBL only.
 */
export function applyStudioLook(THREE, renderer, scene, options = {}) {
  const settings = { ...STUDIO_DEFAULTS, proceduralEnvironment: true, ...options }
  const shadow = createContactShadow(THREE, { intensity: settings.shadowIntensity, softness: settings.shadowSoftness })
  scene.add(shadow.object)
  const fillLights = settings.lights ?? []
  function update(next = {}) {
    Object.assign(settings, next)
    applyToneMapping(THREE, renderer, settings)
    fillLights.forEach((light) => { light.visible = settings.fillLights })
    if (next.shadowSoftness !== undefined) shadow.setSoftness(settings.shadowSoftness)
    if (next.shadowIntensity !== undefined) shadow.setIntensity(settings.shadowIntensity)
  }
  update()
  return {
    shadow,
    settings,
    update,
    dispose() { shadow.dispose() },
  }
}
