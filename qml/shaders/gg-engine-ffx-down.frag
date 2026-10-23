// GgEngine FFXGlow Box4; independently adapted from MIT original WGSL.
vec3 toGamma(vec3 c) {
    return mix(1.055*pow(max(c,vec3(0.0)),vec3(1.0/2.4))-.055,12.92*c,lessThanEqual(c,vec3(.0031308)));
}
vec4 sourceAt(vec2 uv) {
    vec4 c=texture(INPUT,uv);
    if (!gammaInput) c.rgb=toGamma(c.rgb);
    return min(c,vec4(1.0));
}
void MAIN() {
    vec2 t=1.0/INPUT_SIZE;
    t.y*=-FRAMEBUFFER_Y_UP;
    FRAGCOLOR=.25*(sourceAt(INPUT_UV+vec2(-1.5,-1.5)*t)+sourceAt(INPUT_UV+vec2(.5,-1.5)*t)
        +sourceAt(INPUT_UV+vec2(.5,.5)*t)+sourceAt(INPUT_UV+vec2(-1.5,.5)*t));
}
