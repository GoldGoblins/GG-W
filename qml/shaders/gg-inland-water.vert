// Native page origins are multiples of 1024 m; these UVs stay continuous
// across page boundaries. Water levels and geometry remain the saved surface.
VARYING vec2 vInlandUv;
VARYING vec3 vInlandTint;
void MAIN() {
    vInlandUv = VERTEX.xz / 64.0;
    vInlandTint = COLOR.rgb;
}
