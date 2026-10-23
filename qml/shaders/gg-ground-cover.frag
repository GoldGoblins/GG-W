VARYING vec2 vFoliageUv;
void MAIN() {
    vec4 plant = texture(foliageMap, vFoliageUv);
    if (plant.a < 0.45) discard;
    BASE_COLOR = vec4(plant.rgb, 1.0);
    ROUGHNESS = 1.0;
    METALNESS = 0.0;
    SPECULAR_AMOUNT = 0.0;
}
