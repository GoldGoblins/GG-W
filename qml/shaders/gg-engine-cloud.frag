// Original cloud.wgsl: premultiplied gamma texels, authored dome rim fade.
VARYING vec2 vCloudUv;
VARYING float vCloudAlpha;
void MAIN() {
    vec4 t=texture(uTexture,vCloudUv);float alpha=t.a*vCloudAlpha;
    FRAGCOLOR=vec4(t.rgb*alpha,alpha);
}
