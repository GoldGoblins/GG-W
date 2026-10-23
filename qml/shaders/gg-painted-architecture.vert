VARYING vec3 vPaintPosition;
VARYING vec3 vPaintNormal;
VARYING vec3 vPaintColor;
void MAIN() {
    // Object-local colour and brush coordinates stay attached to the shared
    // mesh under native instancing, camera rotation and world-origin shifts.
    vPaintPosition = VERTEX;
    vPaintNormal = NORMAL;
    vPaintColor = COLOR.rgb;
}
