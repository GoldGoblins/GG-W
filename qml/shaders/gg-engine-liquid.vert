VARYING vec2 vLiquidUv;
VARYING vec4 vLiquidColor;
VARYING vec3 vLiquidNormal;
VARYING vec3 vLiquidWorld;
VARYING float vLiquidEyeDepth;
void MAIN() {
    vec4 world=MODEL_MATRIX*vec4(VERTEX,1.0);
    vLiquidWorld=world.xyz;
    vLiquidNormal=normalize(NORMAL_MATRIX*NORMAL);
    vLiquidEyeDepth=-(VIEW_MATRIX*world).z;
    vLiquidUv=UV0;
    vLiquidColor=COLOR;
    POSITION=VIEWPROJECTION_MATRIX*world;
}
