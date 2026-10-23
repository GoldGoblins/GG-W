// Original sequential layer composition and MCSH diffuse factor.
VARYING vec3 vEngineNormal;
VARYING vec3 vEnginePosition;
VARYING vec4 vEngineColor;
VARYING vec2 vEngineUv;
VARYING vec3 vEnginePointLight;
VARYING float vEngineEyeDepth;
// Authored levels remain separate rectangles in a level-zero atlas.
// Explicit bilinear fetches cannot bleed into an adjacent level or frame.
vec4 mipRectangle(int level, int row, vec2 grid, vec2 cell) {
    vec4 r=texelFetch(uMipTable,ivec2(level,row),0);
    r.zw/=grid;r.xy+=cell*r.zw;return r;
}
vec4 mipTexel(sampler2D source, vec2 uv, vec4 r, bool wrap) {
    ivec2 size=ivec2(r.zw),base=ivec2(r.xy);
    vec2 p=uv*vec2(size)-vec2(.5),weight=fract(p);
    ivec2 lo=ivec2(floor(p)),hi=lo+ivec2(1);
    if (wrap) {
        lo=ivec2(mod(vec2(lo),vec2(size)));hi=ivec2(mod(vec2(hi),vec2(size)));
    } else {
        lo=clamp(lo,ivec2(0),size-ivec2(1));hi=clamp(hi,ivec2(0),size-ivec2(1));
    }
    vec4 a=mix(texelFetch(source,base+lo,0),texelFetch(source,base+ivec2(hi.x,lo.y),0),weight.x);
    vec4 b=mix(texelFetch(source,base+ivec2(lo.x,hi.y),0),texelFetch(source,base+hi,0),weight.x);
    return mix(a,b,weight.y);
}
vec4 authoredMip(sampler2D source,vec2 uv,int row,int count,bool wrap,vec2 grid,vec2 cell,bool frameUv) {
    vec4 base=mipRectangle(0,row,grid,cell);
    float footprint=max(length(dFdx(uv)*base.zw),length(dFdy(uv)*base.zw));
    float lod=clamp(log2(max(footprint,1.0)),0.0,float(count-1));
    vec2 sampleUv=frameUv ? fract(uv) : uv;
    if (!uTrilinear) return mipTexel(source,sampleUv,mipRectangle(int(floor(lod+.5)),row,grid,cell),wrap);
    int low=int(floor(lod)),high=min(low+1,count-1);
    return mix(mipTexel(source,sampleUv,mipRectangle(low,row,grid,cell),wrap),
               mipTexel(source,sampleUv,mipRectangle(high,row,grid,cell),wrap),fract(lod));
}
void MAIN() {
    if (uFarClip>0.0 && vEngineEyeDepth>uFarClip) discard;
    vec2 tiled=vEngineUv*uTiling;
    vec2 auv=clamp(vEngineUv,vec2(0.5/64.0),vec2(1.0-0.5/64.0));
    vec3 alpha=texture(uAlphaMap,auv).rgb;
    vec3 color=(uMipCounts.x>0.0 ? authoredMip(uTexture,tiled,0,int(uMipCounts.x),true,vec2(1),vec2(0),false) : texture(uTexture,tiled)).rgb;
    vec3 layer1=(uMipCounts.y>0.0 ? authoredMip(uLayer1,tiled,1,int(uMipCounts.y),true,vec2(1),vec2(0),false) : texture(uLayer1,tiled)).rgb;
    vec3 layer2=(uMipCounts.z>0.0 ? authoredMip(uLayer2,tiled,2,int(uMipCounts.z),true,vec2(1),vec2(0),false) : texture(uLayer2,tiled)).rgb;
    vec3 layer3=(uMipCounts.w>0.0 ? authoredMip(uLayer3,tiled,3,int(uMipCounts.w),true,vec2(1),vec2(0),false) : texture(uLayer3,tiled)).rgb;
    color=mix(color,layer1,alpha.r);
    color=mix(color,layer2,alpha.g);
    color=mix(color,layer3,alpha.b);
    float shadowLit=1.0-texture(uShadowMap,auv).r;
    vec3 primary=clamp(uAmbient+uDiffuse*max(dot(normalize(vEngineNormal),normalize(uToLight)),0.0),0.0,1.0);
    color=clamp(color*primary*(0.3*shadowLit+0.7),0.0,1.0);
    float fog=clamp((vEngineEyeDepth-uFogNear)/max(0.001,uFogFar-uFogNear),0.0,1.0);
    FRAGCOLOR=vec4(mix(color,uFogColor,fog),1.0);
}
