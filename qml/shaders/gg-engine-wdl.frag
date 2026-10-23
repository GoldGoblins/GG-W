VARYING float vWdlEyeDepth;
VARYING float vWdlWallDepth;
void MAIN() {
    if (vWdlEyeDepth<uFarClip-33.0) discard;
    // White under the hull's own 0..1 fog pair, rather than the scene distances.
    FRAGCOLOR=vec4(uFogEnabled ? uFogColor : vec3(1.0),1.0);
    // Original reverse-Z push converted to Qt's finite, forward-depth projection:
    // just behind the detailed wall, strictly before the sky's depth of 1.
    float push=vWdlWallDepth+.001*(1.0-vWdlWallDepth);
    gl_FragDepth=max(gl_FragCoord.z,push);
}
