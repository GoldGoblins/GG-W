VARYING vec3 vSkyDirection;
void MAIN() {
    vSkyDirection = normalize(VERTEX);
    POSITION = MODELVIEWPROJECTION_MATRIX * vec4(VERTEX,1.0);
}
