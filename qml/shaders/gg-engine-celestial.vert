VARYING vec2 vCelestialUv;
VARYING float vCelestialHeight;
void MAIN() {
    vec3 p=uDirection+(uRight*VERTEX.x+uUp*VERTEX.y)*uSize;
    vCelestialUv=UV0;vCelestialHeight=normalize(p).y;
    POSITION=MODELVIEWPROJECTION_MATRIX*vec4(p,1.0);
    POSITION.z=POSITION.w;
}
