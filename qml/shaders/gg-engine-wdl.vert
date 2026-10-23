// Original WDL backdrop; the fragment stage owns the 33-yard seam and depth clamp.
VARYING float vWdlEyeDepth;
VARYING float vWdlWallDepth;
void MAIN() {
    vec4 world=MODEL_MATRIX*vec4(VERTEX,1.0);
    vWdlEyeDepth=-(VIEW_MATRIX*world).z;
    vec4 wall=PROJECTION_MATRIX*vec4(0.0,0.0,-uFarClip,1.0);
    // QRhi's projection already includes its clip-depth conversion.
    float ndc=wall.z/wall.w;
    vWdlWallDepth=NEAR_CLIP_VALUE<0.0 ? ndc*.5+.5 : ndc;
    POSITION=VIEWPROJECTION_MATRIX*world;
}
