// Single world→pixel convention shared by the heatmap overlay (and any future
// world-space overlay). Mirrors EEP's _world_to_px (api/routers/draft.py):
//   image_px = world_m * pixels_per_meter + origin   (origin is in image pixels)
//
// Zones arrive from the API already in image pixels (the backend pre-projects via
// _world_to_px), so the heatmap converts its world-metre rects to the SAME image-
// pixel space here, then both go through the identical image-px→canvas transform.
// This is the one E3 alignment convention — do not add a second formula.
export function worldToImagePx(floorPlan) {
  const ppm = floorPlan?.pixels_per_meter || 1
  const ox = floorPlan?.origin_x || 0
  const oy = floorPlan?.origin_y || 0
  return (wx, wy) => [wx * ppm + ox, wy * ppm + oy]
}
