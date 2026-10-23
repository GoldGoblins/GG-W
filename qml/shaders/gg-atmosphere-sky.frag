VARYING vec3 vSkyDirection;
float skyHash(vec2 cell) {
    return fract(sin(dot(cell,vec2(127.1,311.7)))*43758.5453);
}
void MAIN() {
    vec3 direction=normalize(vSkyDirection);
    float elevation = direction.y;
    vec3 sky = mix(uHorizonColor.rgb,uTopColor.rgb,smoothstep(.025,.42,elevation));
    vec3 ground = mix(uHorizonColor.rgb,uBottomColor.rgb,smoothstep(.03,.70,-elevation));
    // Rounded cloud clusters on an infinite sky plane: world-direction based,
    // never attached to the camera heading, no animated cubemap generation.
    vec2 cloudUV=direction.xz/max(.12,elevation)*1.3+vec2(uTime*.002,0.0);
    vec2 cell=floor(cloudUV),p=fract(cloudUV)-.5;
    float seed=skyHash(cell);
    p.x*=.7;
    float cluster=min(length(p-vec2(-.13,0.0))-.17,
        min(length(p-vec2(.05,.06))-.23,length(p-vec2(.23,-.03))-.16));
    float cloud=(1.0-smoothstep(-.035,.07,cluster))*step(.67,seed)
        *smoothstep(.10,.24,elevation)*(1.0-smoothstep(.70,.92,elevation));
    sky=mix(sky,uCloudColor.rgb,cloud*(.70-uNight*.24));
    // Sparse PS2-style pinpricks: additive only at night, no particle pool.
    vec2 starUV=direction.xz/max(.15,elevation)*52.0;
    float starSeed=skyHash(floor(starUV));
    float star=(1.0-smoothstep(.045,.105,length(fract(starUV)-.5)))
        *step(.985,starSeed)*smoothstep(.12,.35,elevation)*uNight;
    sky+=vec3(.65,.77,1.0)*star*.9;
    FRAGCOLOR = vec4(elevation >= 0.0 ? sky : ground,1.0);
}
