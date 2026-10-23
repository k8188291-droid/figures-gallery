// Keep pointing feedback without rendering a controller body.
export function createControllerVisual(THREE, controller) {
  const beamMaterial = new THREE.MeshBasicMaterial({ color: 0xd9ff43, toneMapped: false, transparent: true, opacity: 0.8, depthTest: false, depthWrite: false })

  // A real 3 mm diameter beam is visible in stereo; WebGL lines are only one pixel wide.
  const geometry = new THREE.CylinderGeometry(0.0015, 0.0015, 1, 8)
  geometry.rotateX(Math.PI / 2)
  geometry.translate(0, 0, -0.5)
  const beam = new THREE.Mesh(geometry, beamMaterial)
  beam.name = 'vr-controller-ray'
  beam.visible = false
  beam.renderOrder = 20
  controller.add(beam)
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.009, 12, 8), beamMaterial)
  tip.visible = false
  tip.renderOrder = 21
  controller.add(tip)

  return {
    beam, tip,
    setHand(hand) {
      const color = hand === 'left' ? 0x55cfff : 0xd9ff43
      beamMaterial.color.setHex(color)
    },
    update(active, distance = 3, hit = false) {
      beam.visible = active && controller.visible
      tip.visible = beam.visible && hit
      beam.scale.z = distance
      tip.position.z = -distance
    },
    dispose() {
      beam.geometry.dispose()
      tip.geometry.dispose()
      beamMaterial.dispose()
      beam.removeFromParent()
      tip.removeFromParent()
    },
  }
}
