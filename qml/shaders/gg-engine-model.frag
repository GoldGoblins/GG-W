// Adapted from GgEngine's wow_model.wgsl; source receipt records renderer differences.
VARYING vec3 vEngineNormal;
VARYING vec3 vEnginePosition;
VARYING vec4 vEngineColor;
VARYING vec2 vEngineUv;
VARYING vec3 vEnginePointLight;
VARYING float vEngineEyeDepth;
vec3 engineNormal(vec3 value) {
    return dot(value,value) > 1e-12 ? normalize(value) : vec3(0.0);
}
vec4 mipRectangle(int level) {
    if (level==0) return uMip0;
    if (level==1) return uMip1;
    if (level==2) return uMip2;
    if (level==3) return uMip3;
    if (level==4) return uMip4;
    if (level==5) return uMip5;
    if (level==6) return uMip6;
    if (level==7) return uMip7;
    if (level==8) return uMip8;
    if (level==9) return uMip9;
    if (level==10) return uMip10;
    if (level==11) return uMip11;
    if (level==12) return uMip12;
    if (level==13) return uMip13;
    if (level==14) return uMip14;
    return uMip15;
}
ivec2 mipPixel(ivec2 pixel,ivec2 size) {
    if (uWrapU) pixel.x=((pixel.x%size.x)+size.x)%size.x; else pixel.x=clamp(pixel.x,0,size.x-1);
    if (uWrapV) pixel.y=((pixel.y%size.y)+size.y)%size.y; else pixel.y=clamp(pixel.y,0,size.y-1);
    return pixel;
}
vec4 mipBilinear(int level,vec2 uv) {
    vec4 r=mipRectangle(level);ivec2 size=ivec2(r.zw);
    vec2 p=vec2(uWrapU?fract(uv.x):clamp(uv.x,0.0,1.0),uWrapV?fract(uv.y):clamp(uv.y,0.0,1.0))*r.zw-vec2(0.5);
    ivec2 a=ivec2(floor(p)),origin=ivec2(r.xy);vec2 f=fract(p);
    vec4 c00=texelFetch(uTexture,origin+mipPixel(a,size),0);
    vec4 c10=texelFetch(uTexture,origin+mipPixel(a+ivec2(1,0),size),0);
    vec4 c01=texelFetch(uTexture,origin+mipPixel(a+ivec2(0,1),size),0);
    vec4 c11=texelFetch(uTexture,origin+mipPixel(a+ivec2(1,1),size),0);
    return mix(mix(c00,c10,f.x),mix(c01,c11,f.x),f.y);
}
vec4 authoredTexture(vec2 uv) {
    if (uMipCount==0) return texture(uTexture,uv);
    vec2 base=uMip0.zw;
    float footprint=max(length(dFdx(uv)*base),length(dFdy(uv)*base));
    float lod=clamp(log2(max(footprint,1e-8)),0.0,float(uMipCount-1));
    if (!uTrilinear) return mipBilinear(int(floor(lod+0.5)),uv);
    int lo=int(floor(lod)),hi=min(lo+1,uMipCount-1);
    return mix(mipBilinear(lo,uv),mipBilinear(hi,uv),fract(lod));
}
void MAIN() {
    if (uFarClip>0.0 && vEngineEyeDepth>uFarClip) discard;
    vec2 uv = vEngineUv * uUvScale + uUvOffset;
    if (uUvPivoted) {
        uv = (vEngineUv + uUvOffset - vec2(0.5)) * uUvScale;
        uv = vec2(uUvRotation.x * uv.x - uUvRotation.y * uv.y,
                  uUvRotation.y * uv.x + uUvRotation.x * uv.y) + vec2(0.5);
    }
    vec4 texel = authoredTexture(uv);
    if (uFadeAlphaKey && texel.a < 224.0/255.0) discard;
    float mu = dot(engineNormal(vEngineNormal), uToLight/max(length(uToLight),0.000001));
    float lobe = uModelKind == 1 ? (4.0 / 17.0) * (0.375 + 2.0 * mu + 1.875 * mu * mu) : max(mu, 0.0);
    vec3 light = uUnlit || uBlendMode >= 5 ? vec3(1.0) : clamp(uAmbient + (uPointLight ? vEnginePointLight : uDiffuse * lobe), 0.0, 1.0);
    if (uPropProbe && !uUnlit && uBlendMode < 5) {
        vec3 n=engineNormal(vEngineNormal);
        vec4 n1=vec4(n,1.0),q=vec4(n.x*n.y,n.y*n.z,n.z*n.z,n.x*n.z);
        light=clamp(vec3(dot(uProbe0,n1)+dot(uProbe3,q),dot(uProbe1,n1)+dot(uProbe4,q),
                         dot(uProbe2,n1)+dot(uProbe5,q))+uProbe6.xyz*(n.x*n.x-n.y*n.y),0.0,1.0);
    }
    if (uWmoInterior) {
        if (uWmoWindow) {
            vec3 midpoint=0.5*(uAmbient+uDiffuse);
            light=clamp(midpoint+vec3(16.0/255.0)+midpoint*max(mu,0.0),0.0,1.0);
        }
        if (uWmoClass == 1) light=mix(vec3(1.0),light,vEngineColor.a);
        if (uWmoClass == 2) light=vec3(1.0+4.0*(uVertexColors ? vEngineColor.a : 0.0));
    }
    float emissionWeight=uUnlit ? 0.0 : uWmoInterior && uWmoClass == 1 ? vEngineColor.a : 1.0;
    vec3 primary=clamp(light*uTint*vEngineColor.rgb+uNightEmissive*emissionWeight,0.0,1.0);
    vec3 gammaColor=texel.rgb*primary;
    if (uWmoInterior && uWmoClass == 2) gammaColor=clamp(light*texel.rgb*uTint*vEngineColor.rgb,0.0,1.0);
    float distanceToCamera = length(vEnginePosition - uCameraPosition);
    float fade = 1.0 - clamp((distanceToCamera-uFadeNear)/max(0.0001,uFadeFar-uFadeNear),0.0,1.0);
    float alpha = clamp(texel.a * uAlpha * (uWmoInterior ? 1.0 : vEngineColor.a) * fade,0.0,1.0);
    if (uBlendMode == 1 && alpha < 224.0/255.0) discard;
    if (uBlendMode <= 1) alpha = 1.0;
    float fogDistance = uPlanarFog ? vEngineEyeDepth : distanceToCamera;
    float fog = clamp((fogDistance-uFogNear)/max(0.001,uFogFar-uFogNear),0.0,1.0);
    // Add fades to black, mod fades to multiplicative identity; opaque/alpha use fog colour.
    vec3 fogTarget = uBlendMode == 3 || uBlendMode == 4 ? vec3(0.0)
        : uBlendMode == 5 ? vec3(1.0) : uBlendMode == 6 ? vec3(0.5) : uFogColor;
    gammaColor = mix(gammaColor,fogTarget,fog);
    FRAGCOLOR = vec4(gammaColor,alpha);
}
