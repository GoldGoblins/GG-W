VARYING vec2 vFoliageUv;
void MAIN() {
    vFoliageUv = vec2(VERTEX.x / 1.8 + 0.5, VERTEX.y / 1.2);
    float bend = sin(uTime * 1.7 + MODEL_MATRIX[3].x * 0.13) * VERTEX.y * VERTEX.y * 0.025;
    VERTEX = vec3(uCameraRight.x * (VERTEX.x + bend), VERTEX.y,
                  uCameraRight.z * (VERTEX.x + bend));
    // Ground-facing normals keep an upright card from going black when its
    // display orientation changes. Its world origin never changes.
    NORMAL = vec3(0.0, 1.0, 0.0);
}
