// Read availability only: do not retain the user's physical position or orientation.
export function inspectTracking(frame, source, referenceSpace) {
  const visibility = frame?.session?.visibilityState
  if (visibility && visibility !== 'visible') return { state: 'paused', visibility }
  if (!frame?.getPose || !source || !referenceSpace) return { state: 'unknown' }
  try {
    const aim = source.targetRaySpace ? Boolean(frame.getPose(source.targetRaySpace, referenceSpace)) : false
    const grip = source.gripSpace ? Boolean(frame.getPose(source.gripSpace, referenceSpace)) : false
    return { state: 'available', aim, grip }
  } catch (error) {
    return { state: 'error', error: error.name }
  }
}
