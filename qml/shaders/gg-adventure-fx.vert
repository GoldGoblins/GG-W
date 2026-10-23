VARYING vec4 vFxColor;
VARYING vec2 vFxUV;
VARYING float vFxDistance;
VARYING float vFxBeacon;
void MAIN() {
    vFxColor = COLOR;
    // UV.x tags: 0=world FX, 2=beacon, 4/6=weapon-local clouds.
    // The current weapon matrices follow native bone animation, even while
    // simulation snapshots or particle buffers are paused.
    float tag=floor(UV0.x*.5);
    vFxBeacon=tag==1.0 ? 1.0 : 0.0;
    vFxUV = vec2(UV0.x-tag*2.0,UV0.y);
    vec4 world=MODEL_MATRIX*vec4(VERTEX,1.0);
    if (tag==2.0) world=uEnchantMatrix0*vec4(VERTEX,1.0);
    else if (tag==3.0) world=uEnchantMatrix1*vec4(VERTEX,1.0);
    vFxDistance = length(world.xyz - uCameraPosition);
    // Unshaded materials supply their own clip-space position.
    POSITION = VIEWPROJECTION_MATRIX * world;
}
