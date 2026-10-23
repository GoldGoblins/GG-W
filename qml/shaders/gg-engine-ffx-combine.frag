vec3 toGamma(vec3 c) {
    return mix(1.055*pow(max(c,vec3(0.0)),vec3(1.0/2.4))-.055,12.92*c,lessThanEqual(c,vec3(.0031308)));
}
vec3 toLinear(vec3 c) {
    return mix(pow((c+.055)/1.055,vec3(2.4)),c/12.92,lessThanEqual(c,vec3(.04045)));
}
void MAIN() {
    vec2 uv=INPUT_UV;
    if (underwaterWave && !ghost) {
        float c=cos(.174532925),s=sin(.174532925);
        vec2 logicalUV=vec2(uv.x,FRAMEBUFFER_Y_UP>0.0 ? 1.0-uv.y : uv.y);
        vec2 p=vec2(c*logicalUV.x-s*logicalUV.y,s*logicalUV.x+c*logicalUV.y)*vec2(INPUT_SIZE.x,.88*INPUT_SIZE.y)/128.0;
        float ms=floor(max(timeSeconds,0.0)*1000.0);
        p+=vec2(mod(ms,3174.0)/3174.0,mod(ms,2805.0)/2805.0);
        vec2 offset=(texture(waveLut,p).rg-.5)*2.0*3.0/INPUT_SIZE;
        offset.y*=-FRAMEBUFFER_Y_UP;uv+=offset;
    }
    vec4 scene=texture(INPUT,uv);
    vec3 screen=clamp(gammaInput ? scene.rgb : toGamma(scene.rgb),0.0,1.0);
    vec3 blurred=max(texture(blurTexture,uv).rgb,vec3(0.0));
    vec3 outGamma;
    if (ghost) {
        float luma=clamp(dot(screen+glowWeight*blurred*blurred,vec3(.299,.587,.144)),0.0,1.0);
        float p=clamp(4.0*luma*(1.0-luma),0.0,1.0);
        outGamma=min(vec3(luma)+vec3(83.0,147.0,168.0)/255.0*p,vec3(1.0));
    } else outGamma=min(mix(screen,min(blurred,vec3(1.0)),hazeWeight)+glowWeight*blurred*blurred,vec3(1.0));
    // Qt's final linear tonemap supplies the single present encode. World
    // alpha is opaque; model-widget callers can retain their transparent clear.
    FRAGCOLOR=vec4(toLinear(clamp(outGamma,0.0,1.0)),opaqueOutput ? 1.0 : scene.a);
}
