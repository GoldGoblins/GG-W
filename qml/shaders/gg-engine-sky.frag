// Original engine-world/src/shaders/sky.wgsl, Qt axes and material interface.
VARYING vec3 vSkyDirection;
float azimuthGlow(float phase) {
    float p=fract(phase);
    if (p<.125) return mix(0.0,1.0,(p+.125)/.25);
    if (p<.375) return mix(1.0,0.0,(p-.125)/.25);
    if (p<.5) return mix(0.0,-.5,(p-.375)/.125);
    if (p<.625) return mix(-.5,-.7,(p-.5)/.125);
    if (p<.75) return mix(-.7,-.5,(p-.625)/.125);
    if (p<.875) return mix(-.5,0.0,(p-.75)/.125);
    return mix(0.0,1.0,(p-.875)/.25);
}
vec3 warped(vec3 base,float g) {
    float s2=uWarp*uWarp;
    return g>=0.0 ? mix(base,uSky1,(1.0-g)*s2) : mix(mix(base,uSky1,uWarp),uSky0,.7*(-g)*s2);
}
void MAIN() {
    vec3 dir=normalize(vSkyDirection);
    float elev=degrees(asin(clamp(dir.y,-1.0,1.0)));
    vec3 s1=uSky1,s2=uSky2,s3=uSky3,s4=uSky4;
    if (uWarp>0.0) {
        float az=fract((atan(dir.z,dir.x)-uSunAzimuth)/6.2831853+.125);
        float seg=az*24.0,k=floor(seg),f=seg-k;
        float g0=azimuthGlow(k/24.0),g1=azimuthGlow((k+1.0)/24.0);
        s1=mix(warped(uSky1,g0),warped(uSky1,g1),f);
        s2=mix(warped(uSky2,g0),warped(uSky2,g1),f);
        s3=mix(warped(uSky3,g0),warped(uSky3,g1),f);
        s4=mix(warped(uSky4,g0),warped(uSky4,g1),f);
    }
    vec3 col=elev<=0.0 ? uFog : elev<1.8 ? mix(uFog,s4,elev/1.8)
        : elev<3.7 ? mix(s4,s3,(elev-1.8)/1.9) : elev<9.8 ? mix(s3,s2,(elev-3.7)/6.1)
        : elev<16.8 ? mix(s2,s1,(elev-9.8)/7.0) : mix(s1,uSky0,(elev-16.8)/73.2);
    FRAGCOLOR=vec4(col,1.0);
}
