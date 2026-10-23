VARYING vec2 vWeatherUv;
VARYING vec4 vWeatherColor;
VARYING float vWeatherDepth;
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
    if (uFarClip>0.0 && vWeatherDepth>uFarClip) discard;
    vec4 texel=(uMipCount>0 ? authoredMip(uTexture,vWeatherUv,0,uMipCount,false,vec2(1),vec2(0),false) : texture(uTexture,vWeatherUv))*vWeatherColor;
    if (uLayer<2) {
        if (uSceneFog) texel.rgb=mix(texel.rgb,vec3(.50196078),clamp((vWeatherDepth-uFogNear)/max(.001,uFogFar-uFogNear),0.0,1.0));
        float fog=clamp((vWeatherDepth-70.0)/5.0,0.0,1.0);
        texel.rgb=mix(texel.rgb,vec3(.50196078),fog);
    }
    FRAGCOLOR=texel;
}
