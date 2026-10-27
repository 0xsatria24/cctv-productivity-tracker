export const DEFAULT_WORKSTATION_RULES={occupied_confirm_seconds:2,empty_confirm_seconds:5,
  max_evidence_gap_seconds:1,association_overlap:.25,ambiguity_margin:.1,strong_confidence:.5};
export const ANALYSIS_JPEG_QUALITY=.9;

export function workstationIntervalMs(fps) {
  return 1000/(Number.isFinite(fps)&&fps>=.5&&fps<=30?fps:2);
}

export function analysisCaptureSize(width,height) {
  const scale=Math.min(1,960/Math.max(width,height),Math.sqrt(1280*720/(width*height)));
  return {width:Math.max(1,Math.round(width*scale)),height:Math.max(1,Math.round(height*scale))};
}
