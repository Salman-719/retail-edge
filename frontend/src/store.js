import { create } from 'zustand'

function inferMaxStep(data) {
  if (!data.floorPlan?.url) return 1
  if (!data.scale?.pixelsPerMeter) return 2
  if (!data.zones?.length) return 3
  if (!data.cameras?.length) return 4
  if (!data.cameras?.some(c => c.videoPath || c.videoDuration)) return 5
  if (!data.cameras?.some(c => c.correspondences?.length >= 4)) return 6
  if (!data.cameras?.some(c => c.homographyMatrix)) return 7
  return 9
}

const useStore = create((set, get) => ({
  // Active store (DB entity)
  activeStoreId: null,
  activeStoreName: null,
  setActiveStore: (id, name) => set({ activeStoreId: id, activeStoreName: name }),

  // Step tracking
  currentStep: 1,
  maxReachedStep: 1,
  setStep: (n) => set(s => ({
    currentStep: n,
    maxReachedStep: Math.max(s.maxReachedStep, n),
  })),

  // Step 1: Floor plan
  floorPlanUrl: null,
  floorPlanWidth: 0,
  floorPlanHeight: 0,

  // Step 2: Scale
  origin: null,
  scalePoints: null,
  realWorldDistance: null,
  pixelsPerMeter: null,

  // Step 3: Zones & Obstacles
  zones: [],
  obstacles: [],

  // Step 4+: Cameras
  cameras: [],

  // Setters
  setFloorPlan: (data) => set(data),
  setScale: (data) => set(data),

  addZone: (zone) => set(s => ({ zones: [...s.zones, zone] })),
  removeZone: (id) => set(s => ({ zones: s.zones.filter(z => z.id !== id) })),
  updateZone: (id, patch) => set(s => ({ zones: s.zones.map(z => z.id === id ? { ...z, ...patch } : z) })),

  addObstacle: (obs) => set(s => ({ obstacles: [...s.obstacles, obs] })),
  removeObstacle: (id) => set(s => ({ obstacles: s.obstacles.filter(o => o.id !== id) })),

  addCamera: (cam) => set(s => ({ cameras: [...s.cameras, cam] })),
  removeCamera: (id) => set(s => ({ cameras: s.cameras.filter(c => c.id !== id) })),
  updateCamera: (id, patch) => set(s => ({
    cameras: s.cameras.map(c => c.id === id ? { ...c, ...patch } : c),
  })),

  loadProject: (data) => {
    const maxStep = inferMaxStep(data)
    set({
      floorPlanUrl: data.floorPlan?.url ?? null,
      floorPlanWidth: data.floorPlan?.widthPx ?? 0,
      floorPlanHeight: data.floorPlan?.heightPx ?? 0,
      origin: data.scale?.originPx ?? null,
      scalePoints: data.scale ? { p1: data.scale.scalePoint1Px, p2: data.scale.scalePoint2Px } : null,
      realWorldDistance: data.scale?.realWorldDistanceM ?? null,
      pixelsPerMeter: data.scale?.pixelsPerMeter ?? null,
      zones: data.zones ?? [],
      obstacles: data.obstacles ?? [],
      cameras: data.cameras ?? [],
      currentStep: maxStep,
      maxReachedStep: maxStep,
    })
  },

  resetOnboarding: () => set({
    currentStep: 1,
    maxReachedStep: 1,
    floorPlanUrl: null,
    floorPlanWidth: 0,
    floorPlanHeight: 0,
    origin: null,
    scalePoints: null,
    realWorldDistance: null,
    pixelsPerMeter: null,
    zones: [],
    obstacles: [],
    cameras: [],
  }),

  getProjectData: () => {
    const s = get()
    return {
      version: '1.0',
      savedAt: new Date().toISOString(),
      floorPlan: {
        url: s.floorPlanUrl,
        widthPx: s.floorPlanWidth,
        heightPx: s.floorPlanHeight,
      },
      scale: s.origin ? {
        originPx: s.origin,
        scalePoint1Px: s.scalePoints?.p1,
        scalePoint2Px: s.scalePoints?.p2,
        realWorldDistanceM: s.realWorldDistance,
        pixelsPerMeter: s.pixelsPerMeter,
      } : null,
      zones: s.zones,
      obstacles: s.obstacles,
      cameras: s.cameras,
    }
  },
}))

export default useStore
