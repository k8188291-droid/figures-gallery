import { createControllerVisual } from './vrControllerVisual'
import { inspectTracking } from './vrTracking'

// All distances in this room are metres. Source GLBs are never modified on disk.
export function createVRStage(THREE, renderer, scene, { onNavigate, onExit, onControllerStatus }) {
  const room = new THREE.Group()
  room.visible = false
  scene.add(room)
  const holder = new THREE.Group()
  room.add(holder)
  const raycaster = new THREE.Raycaster()
  const rotation = new THREE.Matrix4()
  // Grabbing needs an object hit, not a surface triangle. Cache the bounds in
  // holder space, then transform each ray instead of traversing the GLB meshes.
  const modelBounds = new THREE.Box3()
  const inverseHolder = new THREE.Matrix4()
  const modelRay = new THREE.Ray()
  const modelHitPoint = new THREE.Vector3()
  const modelHit = { object: holder, distance: 0 }
  const buttonHits = []
  const buttons = []
  const controllers = []
  let model = null
  let size = new THREE.Vector3(1, 1, 1)
  let displaySize = 0.45
  let heldBy = null
  let heldWith = null
  let heldSource = null
  let grabTime = null
  // Only this empty target follows the raw controller. The visible model stays
  // under the room and interpolates towards it, including controller rotation.
  const grabTarget = new THREE.Object3D()
  const grabMatrix = new THREE.Matrix4()
  const grabPosition = new THREE.Vector3()
  const grabRotation = new THREE.Quaternion()
  const grabScale = new THREE.Vector3()
  let rotationBy = null
  let rotationActive = false
  let rotationGrip = null
  const rotationStartInverse = new THREE.Quaternion()
  const rotationModelStart = new THREE.Quaternion()
  const rotationWorld = new THREE.Quaternion()
  const roomWorldRotation = new THREE.Quaternion()
  const controllerWorldRotation = new THREE.Quaternion()
  let placementPending = false
  let floorTracked = true
  let modelName = ''
  let status = 'Loading model…'
  let canNavigate = false
  let controllerStatus = ''
  let sessionVisibility = 'visible'

  const mesh = (geometry, color, parent = room) => {
    const object = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color, roughness: 0.85 }))
    parent.add(object)
    return object
  }
  const floor = mesh(new THREE.CircleGeometry(8, 96), 0x151b20)
  floor.rotation.x = -Math.PI / 2
  const grid = new THREE.GridHelper(16, 32, 0x3b4b4e, 0x263237)
  grid.position.y = 0.002
  room.add(grid)
  const pedestal = mesh(new THREE.CylinderGeometry(0.46, 0.55, 0.88, 64), 0x242e32)
  pedestal.position.set(0, 0.44, -1.3)
  const top = mesh(new THREE.CylinderGeometry(0.49, 0.49, 0.035, 64), 0x4c5a56)
  top.position.set(0, 0.9, -1.3)
  const rim = new THREE.Mesh(new THREE.TorusGeometry(0.48, 0.005, 8, 64), new THREE.MeshBasicMaterial({ color: 0xd9ff43 }))
  rim.rotation.x = Math.PI / 2
  rim.position.set(0, 0.92, -1.3)
  room.add(rim)

  const panel = new THREE.Group()
  panel.name = 'vr-menu'
  panel.scale.setScalar(0.25)
  panel.position.set(0, 0.77, -0.62)
  panel.rotation.x = -0.65
  room.add(panel)

  function label(width, height, parent, background = '#202b30') {
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(width * 900)
    canvas.height = Math.round(height * 900)
    const context = canvas.getContext('2d')
    const texture = new THREE.CanvasTexture(canvas)
    texture.colorSpace = THREE.SRGBColorSpace
    const object = new THREE.Mesh(new THREE.PlaneGeometry(width, height), new THREE.MeshBasicMaterial({ map: texture, toneMapped: false }))
    parent.add(object)
    object.userData.paint = (text, accent = false) => {
      object.userData.text = text
      context.fillStyle = accent ? '#d9ff43' : background
      context.fillRect(0, 0, canvas.width, canvas.height)
      context.fillStyle = accent ? '#151b20' : '#edf2eb'
      context.font = `${Math.round(canvas.height * 0.34)}px sans-serif`
      context.textAlign = 'center'
      context.textBaseline = 'middle'
      context.fillText(text, canvas.width / 2, canvas.height / 2, canvas.width - 18)
      texture.needsUpdate = true
    }
    return object
  }
  const title = label(1.12, 0.09, panel)
  title.position.y = 0.29
  const hint = label(1.12, 0.065, panel)
  hint.position.y = -0.27
  hint.userData.paint('Point + trigger to select / Hold trigger or grip to pick up')
  const trackingLabel = label(1.12, 0.075, panel)
  trackingLabel.position.y = -0.35
  trackingLabel.visible = false

  const rotationBall = new THREE.Group()
  rotationBall.name = 'vr-rotation-ball'
  room.add(rotationBall)
  const ballMaterial = new THREE.MeshStandardMaterial({ color: 0x81a8ff, roughness: 0.35, metalness: 0.25, emissive: 0x203563, emissiveIntensity: 0.4 })
  const ballBody = new THREE.Mesh(new THREE.SphereGeometry(0.065, 20, 12), ballMaterial)
  rotationBall.add(ballBody)
  ;[0xff7979, 0x8aefae, 0x91bfff].forEach((color, axis) => {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.069, 0.0025, 6, 40), new THREE.MeshBasicMaterial({ color, toneMapped: false }))
    if (axis === 0) ring.rotation.y = Math.PI / 2
    if (axis === 1) ring.rotation.x = Math.PI / 2
    rotationBall.add(ring)
  })
  const ballLabel = label(0.22, 0.04, room)
  ballLabel.position.set(0.38, 0.89, -0.7)
  ballLabel.userData.paint('Tap grip to hold / release')
  function dockRotationBall() {
    room.add(rotationBall)
    rotationBall.position.set(0.38, 1.02, -0.7)
    rotationBall.quaternion.identity()
    ballMaterial.emissiveIntensity = 0.4
  }
  dockRotationBall()
  const ballSphere = new THREE.Sphere(new THREE.Vector3(), 0.075)
  const ballPoint = new THREE.Vector3()
  const ballHit = { object: rotationBall, distance: 0 }

  // Keep this separate from menu scaling so the small counter stays legible.
  const fpsLabel = label(0.16, 0.045, room)
  fpsLabel.name = 'vr-fps'
  fpsLabel.position.copy(panel.position).add(new THREE.Vector3(0, 0.12, 0).applyQuaternion(panel.quaternion))
  fpsLabel.quaternion.copy(panel.quaternion)
  fpsLabel.userData.paint('-- FPS')
  let fpsStart = null
  let fpsFrames = 0
  function resetFPS() {
    fpsStart = null
    fpsFrames = 0
    fpsLabel.userData.paint('-- FPS')
  }
  function updateFPS(time, visible) {
    fpsLabel.visible = visible
    if (!visible || !Number.isFinite(time)) {
      if (fpsStart !== null) resetFPS()
      return
    }
    if (fpsStart === null || time < fpsStart) {
      fpsStart = time
      fpsFrames = 0
      return
    }
    fpsFrames++
    const elapsed = time - fpsStart
    if (elapsed >= 500) {
      fpsLabel.userData.paint(`${Math.round(fpsFrames * 1000 / elapsed)} FPS`)
      fpsStart = time
      fpsFrames = 0
    }
  }

  function updateControllerStatus(message) {
    if (message === controllerStatus) return
    controllerStatus = message
    trackingLabel.userData.paint(message)
    onControllerStatus?.(message)
  }

  function refreshHint() {
    hint.userData.paint(rotationBy ? (rotationActive ? 'Turn to rotate / Release trigger to reset wrist' : 'Hold trigger to rotate / Tap grip to release ball') : heldBy
      ? 'Stick: distance / size | Other hand: grab rotation ball'
      : 'Point + trigger to select / Hold trigger or grip to pick up')
  }
  function releaseRotation() {
    if (!rotationBy) return
    // Resume primary-hand rotation from the currently displayed angle, not the
    // old angle captured before the second hand took over.
    if (heldBy) {
      heldBy.getWorldQuaternion(controllerWorldRotation).invert()
      holder.getWorldQuaternion(rotationWorld)
      grabTarget.quaternion.copy(controllerWorldRotation).multiply(rotationWorld)
    }
    rotationBy = null
    rotationGrip = null
    rotationActive = false
    dockRotationBall()
    refreshHint()
  }
  function release() {
    releaseRotation()
    if (!heldBy) return
    // Freeze the displayed pose, rather than snapping to the unsmoothed target.
    displaySize = Math.max(holder.scale.x, holder.scale.y, holder.scale.z) * Math.max(size.x, size.y, size.z)
    grabTarget.removeFromParent()
    heldBy = null
    heldWith = null
    heldSource = null
    grabTime = null
    refreshHint()
  }
  function pauseInput(visibility) {
    release()
    controllers.forEach(({ visual }) => visual.update(false))
    updateControllerStatus(`VR input paused (${visibility}) - close SteamVR / VIVE menus`)
  }
  function reset() {
    release()
    const scale = displaySize / Math.max(size.x, size.y, size.z, 0.001)
    holder.scale.setScalar(scale)
    holder.rotation.set(0, -Math.PI / 2, 0)
    holder.position.set(0, 0.925 + size.y * scale / 2, -1.3)
  }
  function scaleBy(factor) {
    displaySize = THREE.MathUtils.clamp(displaySize * factor, 0.12, 2.5)
    reset()
  }
  const actions = [
    ['Previous', () => onNavigate(-1), 'navigate'],
    ['Reset', reset],
    ['Next', () => onNavigate(1), 'navigate'],
    ['Smaller', () => scaleBy(0.8), 'model'],
    ['Tabletop', () => { displaySize = 0.45; reset() }, 'model'],
    ['Larger', () => scaleBy(1.25), 'model'],
    ['Turn 30°', () => { release(); holder.rotation.y += Math.PI / 6 }, 'model'],
    ['Large display', () => { displaySize = 1.25; reset() }, 'model'],
    ['Exit VR', onExit],
  ]
  actions.forEach(([text, action, kind], index) => {
    const button = label(0.35, 0.11, panel)
    button.position.set((index % 3 - 1) * 0.38, 0.15 - Math.floor(index / 3) * 0.135, 0)
    button.userData = { ...button.userData, text, action, kind, enabled: true, hovered: false }
    button.userData.paint(text)
    buttons.push(button)
  })
  function refresh() {
    title.userData.paint(status || modelName)
    rotationBall.visible = Boolean(model)
    ballLabel.visible = Boolean(model)
    buttons.forEach((button) => {
      const enabled = button.userData.kind === 'navigate' ? canNavigate : button.userData.kind === 'model' ? Boolean(model) : true
      button.userData.enabled = enabled
      button.material.opacity = enabled ? 1 : 0.35
      button.material.transparent = true
    })
  }
  function target(controller) {
    controller.updateWorldMatrix(true, false)
    rotation.identity().extractRotation(controller.matrixWorld)
    raycaster.ray.origin.setFromMatrixPosition(controller.matrixWorld)
    raycaster.ray.direction.set(0, 0, -1).applyMatrix4(rotation)
    panel.updateWorldMatrix(true, true)
    buttonHits.length = 0
    raycaster.intersectObjects(buttons, false, buttonHits)
    let nearest = buttonHits[0]
    if (!model) return nearest
    if (!rotationBy && controller !== heldBy) {
      rotationBall.getWorldPosition(ballSphere.center)
      if (raycaster.ray.intersectSphere(ballSphere, ballPoint)) {
        ballHit.distance = raycaster.ray.origin.distanceTo(ballPoint)
        if (!nearest || ballHit.distance < nearest.distance) nearest = ballHit
      }
    }
    holder.updateWorldMatrix(true, false)
    inverseHolder.copy(holder.matrixWorld).invert()
    modelRay.copy(raycaster.ray).applyMatrix4(inverseHolder)
    if (!modelRay.intersectBox(modelBounds, modelHitPoint)) return nearest
    modelHitPoint.applyMatrix4(holder.matrixWorld)
    modelHit.distance = raycaster.ray.origin.distanceTo(modelHitPoint)
    return nearest && nearest.distance <= modelHit.distance ? nearest : modelHit
  }
  function beginRotationGrab(controller, grip) {
    if (!model || rotationBy || heldBy === controller) return
    holder.getWorldQuaternion(rotationModelStart)
    rotationBy = controller
    rotationGrip = grip
    rotationActive = false
    placeBallInHand()
    ballMaterial.emissiveIntensity = 0.8
    if (!heldBy) grabTime = null
    refreshHint()
  }
  function placeBallInHand() {
    const anchor = rotationGrip?.visible ? rotationGrip : rotationBy
    if (rotationBall.parent !== anchor) anchor.add(rotationBall)
    rotationBall.position.set(0, 0, 0)
    rotationBall.quaternion.identity()
  }
  function startRotationTurn() {
    if (rotationActive) return
    // Each trigger press rebases both poses, allowing repeated wrist strokes.
    rotationBy.getWorldQuaternion(rotationStartInverse).invert()
    holder.getWorldQuaternion(rotationModelStart)
    rotationActive = true
    ballMaterial.emissiveIntensity = 1.4
    refreshHint()
  }
  function stopRotationTurn() {
    // Freeze the displayed angle immediately; do not finish a pending smoothing step.
    holder.getWorldQuaternion(rotationModelStart)
    rotationActive = false
    ballMaterial.emissiveIntensity = 0.8
    refreshHint()
  }
  function grab(controller, gesture, source) {
    if (heldBy || !model || rotationBy === controller) return
    grabTarget.position.copy(holder.position)
    grabTarget.quaternion.copy(holder.quaternion)
    grabTarget.scale.copy(holder.scale)
    room.add(grabTarget)
    controller.attach(grabTarget)
    heldBy = controller
    heldWith = gesture
    heldSource = source
    grabTime = null
    refreshHint()
  }
  function stickAxis(value) {
    if (!Number.isFinite(value) || Math.abs(value) <= 0.18) return 0
    return Math.sign(value) * (Math.min(Math.abs(value), 1) - 0.18) / 0.82
  }
  function updateGrab(time) {
    if (!heldBy && !rotationBy) return
    if (heldBy && (!heldBy.visible || !heldSource)) { release(); return }
    if (rotationBy && !rotationBy.visible) releaseRotation()
    const delta = grabTime === null ? 0 : THREE.MathUtils.clamp((time - grabTime) / 1000, 0, 0.05)
    grabTime = time
    const gamepad = heldSource?.gamepad
    const axes = gamepad?.axes || []
    // xr-standard reserves axes 0/1 for a touchpad, 2/3 for a thumbstick.
    // https://www.w3.org/TR/webxr-gamepads-module-1/#xr-standard-gamepad-mapping
    const index = gamepad?.mapping === 'xr-standard' || axes.length >= 4 ? 2 : 0
    const horizontal = stickAxis(axes[index])
    const vertical = stickAxis(axes[index + 1])
    if (vertical) {
      // Negative Y is stick-up: move farther along the controller's -Z ray.
      const distance = -grabTarget.position.z
      const next = THREE.MathUtils.clamp(distance - vertical * 0.8 * delta, Math.min(0.15, distance), Math.max(4, distance))
      grabTarget.position.z = -next
    }
    if (horizontal) {
      const next = THREE.MathUtils.clamp(displaySize * Math.exp(horizontal * 0.9 * delta), 0.12, 2.5)
      grabTarget.scale.multiplyScalar(next / displaySize)
      displaySize = next
    }
    room.updateWorldMatrix(true, false)
    if (heldBy) {
      grabTarget.updateWorldMatrix(true, false)
      grabMatrix.copy(room.matrixWorld).invert().multiply(grabTarget.matrixWorld)
      grabMatrix.decompose(grabPosition, grabRotation, grabScale)
    }
    if (rotationBy) {
      placeBallInHand()
      room.getWorldQuaternion(roomWorldRotation).invert()
      if (rotationActive) {
        rotationBy.getWorldQuaternion(rotationWorld)
        rotationWorld.multiply(rotationStartInverse)
        // Reverse X/Y in the room's axes (initial VR facing), leaving Z intact.
        // Map the relative quaternion, not absolute Euler angles, so each new
        // trigger stroke remains continuous and mixed-axis turns stay stable.
        controllerWorldRotation.copy(roomWorldRotation).invert()
        rotationWorld.premultiply(roomWorldRotation).multiply(controllerWorldRotation)
        rotationWorld.x = -rotationWorld.x
        rotationWorld.y = -rotationWorld.y
        grabRotation.copy(roomWorldRotation).multiply(rotationModelStart).premultiply(rotationWorld)
      } else grabRotation.copy(roomWorldRotation).multiply(rotationModelStart)
    }
    // ~70 ms time constant; frame-rate independent and allocation-free.
    const alpha = 1 - Math.exp(-14 * delta)
    if (heldBy) {
      holder.position.lerp(grabPosition, alpha)
      holder.scale.lerp(grabScale, alpha)
    }
    if (heldBy || rotationBy) holder.quaternion.slerp(grabRotation, alpha)
  }
  for (let index = 0; index < 2; index++) {
    const controller = renderer.xr.getController(index)
    scene.add(controller)
    const grip = renderer.xr.getControllerGrip(index)
    scene.add(grip)
    const visual = createControllerVisual(THREE, controller)
    const entry = { controller, grip, visual, source: null }
    const start = (gesture) => {
      if (!room.visible || !renderer.xr.isPresenting || sessionVisibility !== 'visible' || !controller.visible || !entry.source) return
      if (rotationBy === controller) {
        if (gesture === 'select') startRotationTurn()
        else if (gesture === 'squeeze') releaseRotation()
        return
      }
      if (heldBy === controller) return
      const hit = target(controller)
      if (!hit) return
      if (buttons.includes(hit.object)) {
        if (gesture === 'select' && hit.object.userData.enabled) hit.object.userData.action()
      } else if (hit.object === rotationBall) {
        if (gesture === 'squeeze') beginRotationGrab(controller, grip)
      }
      else grab(controller, gesture, entry.source)
    }
    const selectStart = () => start('select')
    const squeezeStart = () => start('squeeze')
    const end = (gesture) => {
      if (rotationBy === controller && gesture === 'select') stopRotationTurn()
      if (heldBy === controller && heldWith === gesture) release()
    }
    const selectEnd = () => end('select')
    const squeezeEnd = () => end('squeeze')
    const connected = (event) => {
      entry.source = event.data.targetRayMode === 'tracked-pointer' && !event.data.hand ? event.data : null
      visual.setHand(event.data.handedness)
    }
    const disconnected = () => {
      if (rotationBy === controller) releaseRotation()
      if (heldBy === controller) release()
      entry.source = null
      visual.update(false)
    }
    controller.addEventListener('selectstart', selectStart)
    controller.addEventListener('selectend', selectEnd)
    controller.addEventListener('squeezestart', squeezeStart)
    controller.addEventListener('squeezeend', squeezeEnd)
    controller.addEventListener('connected', connected)
    controller.addEventListener('disconnected', disconnected)
    Object.assign(entry, { selectStart, selectEnd, squeezeStart, squeezeEnd, connected, disconnected })
    controllers.push(entry)
  }
  refresh()

  return {
    room,
    setModel(nextModel, nextSize, name) {
      release()
      if (model) model.removeFromParent()
      model = nextModel
      if (model) {
        size.copy(nextSize)
        // The loader centers the model before passing its unscaled dimensions.
        modelBounds.min.copy(size).multiplyScalar(-0.5)
        modelBounds.max.copy(size).multiplyScalar(0.5)
        holder.add(model)
        modelName = name
      }
      reset()
      refresh()
    },
    setStatus(message, navigate) {
      status = message
      canNavigate = navigate
      refresh()
    },
    setVisible(visible) {
      release()
      resetFPS()
      room.visible = visible
      if (visible) reset()
    },
    reset,
    setSessionVisibility(visibility) {
      sessionVisibility = visibility || 'visible'
      if (sessionVisibility !== 'visible') { resetFPS(); pauseInput(sessionVisibility) }
    },
    preparePlacement(hasFloor) { floorTracked = hasFloor; placementPending = true },
    previewPlacement() { room.position.set(0, 0, 0); room.rotation.set(0, 0, 0) },
    click(event, camera) {
      if (!room.visible || renderer.xr.isPresenting) return
      const bounds = renderer.domElement.getBoundingClientRect()
      raycaster.setFromCamera(new THREE.Vector2((event.clientX - bounds.left) / bounds.width * 2 - 1, -(event.clientY - bounds.top) / bounds.height * 2 + 1), camera)
      const hit = raycaster.intersectObjects(buttons)[0]
      if (hit?.object.userData.enabled) hit.object.userData.action()
    },
    update(frame, time = performance.now()) {
      const active = renderer.xr.isPresenting && room.visible
      const visibility = frame?.session?.visibilityState || sessionVisibility
      updateFPS(time, room.visible && (!renderer.xr.isPresenting || visibility === 'visible'))
      trackingLabel.visible = active
      if (!active) {
        controllers.forEach(({ visual }) => visual.update(false))
        return
      }
      if (visibility !== 'visible') { pauseInput(visibility); return }
      if (placementPending && frame) {
        const pose = frame.getViewerPose(renderer.xr.getReferenceSpace())
        if (pose) {
          const { position, orientation } = pose.transform
          const direction = new THREE.Vector3(0, 0, -1).applyQuaternion(new THREE.Quaternion(orientation.x, orientation.y, orientation.z, orientation.w))
          room.position.set(position.x, floorTracked ? 0 : position.y - 1.6, position.z)
          room.rotation.y = Math.atan2(-direction.x, -direction.z)
          placementPending = false
        }
      }
      updateGrab(time)
      const hovered = new Set()
      const tracking = []
      controllers.forEach(({ controller, grip, visual, source }) => {
        if (!source) { visual.update(false); return }
        const hand = source.handedness === 'left' ? 'Left (blue)' : source.handedness === 'right' ? 'Right (green)' : 'Controller'
        let state = controller.visible ? (grip.visible ? 'tracked' : 'aim only') : 'pose unavailable'
        if (!controller.visible) {
          const raw = inspectTracking(frame, source, renderer.xr.getReferenceSpace())
          if (raw.state === 'available') state = `pose unavailable (aim:${raw.aim ? 'yes' : 'no'} grip:${raw.grip ? 'yes' : 'no'})`
          else if (raw.state === 'error') state = `pose unavailable (${raw.error})`
        }
        tracking.push(`${hand}: ${state}`)
        if (!controller.visible) {
          if (heldBy === controller) release()
          visual.update(true)
          return
        }
        const hit = target(controller)
        visual.update(true, hit ? hit.distance : 3, Boolean(hit))
        if (hit && buttons.includes(hit.object) && hit.object.userData.enabled) hovered.add(hit.object)
      })
      const reported = Array.from(renderer.xr.getSession?.()?.inputSources || []).filter((source) => source.targetRayMode === 'tracked-pointer' && !source.hand).length
      const missingMessage = reported ? `WebXR reports ${reported} controllers - waiting for tracking` : 'No controllers received - check VIVE Streaming input settings'
      updateControllerStatus(tracking.length ? tracking.join(' / ') : missingMessage)
      buttons.forEach((button) => {
        const active = hovered.has(button)
        if (button.userData.hovered !== active) {
          button.userData.hovered = active
          button.userData.paint(button.userData.text, active)
        }
      })
    },
    dispose() {
      release()
      controllers.forEach(({ controller, grip, visual, selectStart, selectEnd, squeezeStart, squeezeEnd, connected, disconnected }) => {
        controller.removeEventListener('selectstart', selectStart)
        controller.removeEventListener('selectend', selectEnd)
        controller.removeEventListener('squeezestart', squeezeStart)
        controller.removeEventListener('squeezeend', squeezeEnd)
        controller.removeEventListener('connected', connected)
        controller.removeEventListener('disconnected', disconnected)
        visual.dispose()
        controller.removeFromParent()
        grip.removeFromParent()
      })
    },
  }
}
