// Qt atlas implementation of GgEngine's three liquid renderer equations.
// The depth coordinate is the original per-vertex byte/LUT in COLOR.a.
VARYING vec2 vLiquidUv;
VARYING vec4 vLiquidColor;
VARYING vec3 vLiquidNormal;
VARYING vec3 vLiquidWorld;
VARYING float vLiquidEyeDepth;
vec4 swatchRow(float i) {
    vec4 a=vec4(round(uShallow.rgb*255.0),floor(uShallow.a*255.0));
    vec4 b=vec4(round(uDeep.rgb*255.0),floor(uDeep.a*255.0));
    vec4 row=a+floor(i*(b-a)/64.0);
    if (uOcean && i>=63.0) row=vec4(floor(row.rgb*.9),255.0);
    return row/255.0;
}
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
    if (uFarClip>0.0 && vLiquidEyeDepth>uFarClip) discard;
    float frame=mod(floor(uClock*24.0),float(max(uFrames,1)));
    vec2 cell=vec2(mod(frame,uAtlasGrid.x),floor(frame/uAtlasGrid.x));
    vec2 rawUv=vLiquidUv+vec2(0.0,uScroll ? fract(uClock/10.0) : 0.0);
    vec2 uv=fract(rawUv);
    vec2 halfPixel=.5*uAtlasGrid/uAtlasSize;
    vec4 detail=uMipCount>0 ? authoredMip(uTexture,rawUv,0,uMipCount,false,uAtlasGrid,cell,true)
        : texture(uTexture,(cell+clamp(uv,halfPixel,vec2(1.0)-halfPixel))/uAtlasGrid);
    float depth=clamp(vLiquidColor.a,0.0,1.0);
    vec3 light=clamp(uAmbient+uDiffuse*max(dot(normalize(vLiquidNormal),normalize(uToLight)),0.0),vec3(0.0),vec3(1.0));
    vec3 toEye=uCameraPosition-vLiquidWorld;
    vec3 halfVector=normalize(normalize(uToLight)+normalize(toEye+vec3(1e-8)));
    vec3 sheen=uSpecular*pow(max(dot(normalize(vLiquidNormal),halfVector),0.0),6.0);
    float alpha=mix(uShallow.a,uDeep.a,depth);
    vec3 rgb;
    if (uFullbright) { rgb=detail.rgb;alpha=1.0; }
    else if (uLiquidPath==2) { rgb=clamp(vLiquidColor.rgb+detail.rgb,vec3(0.0),vec3(1.0));alpha=clamp(alpha+detail.a,0.0,1.0); }
    else if (uLiquidPath==1) { rgb=light*uDeep.rgb+detail.rgb+sheen*detail.a; }
    else {
        float row=clamp(depth*64.0-.5,0.0,63.0);
        vec4 swatch=mix(swatchRow(floor(row)),swatchRow(min(floor(row)+1.0,63.0)),fract(row));
        rgb=light*swatch.rgb+detail.rgb+(sheen+vec3(.25))*detail.a;alpha=swatch.a;
    }
    float fog=clamp((uFogFar-vLiquidEyeDepth)/max(uFogFar-uFogNear,.001),0.0,1.0);
    FRAGCOLOR=vec4(mix(uFogColor,clamp(rgb,vec3(0.0),vec3(1.0)),fog),alpha);
}
