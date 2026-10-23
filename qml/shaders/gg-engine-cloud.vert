VARYING vec2 vCloudUv;
VARYING float vCloudAlpha;
void MAIN() {
    vCloudUv=UV0;vCloudAlpha=COLOR.a;
    POSITION=MODELVIEWPROJECTION_MATRIX*vec4(VERTEX,1.0);
    POSITION.z=POSITION.w;
}
