// Original celestial.wgsl horizon cut, vertex fade and gamma blend equations.
VARYING vec2 vCelestialUv;
VARYING float vCelestialHeight;
float vertexAlpha(float height) { float ramp=height*30.0;return ramp<1.0 ? clamp(ramp,0.0,1.0) : uDiscAlpha; }
void MAIN() {
    vec4 t=texture(uTexture,vCelestialUv);float alpha=t.a*uTint.a;
    if (!uGlare) {
        float bottom=max(uSpan.x,0.0);
        alpha*=vCelestialHeight<=0.0 ? 0.0 : mix(vertexAlpha(bottom),vertexAlpha(uSpan.y),clamp((vCelestialHeight-bottom)/max(uSpan.y-bottom,1e-6),0.0,1.0));
    }
    FRAGCOLOR=vec4(t.rgb*uTint.rgb*alpha,uGlare ? 0.0 : alpha);
}
