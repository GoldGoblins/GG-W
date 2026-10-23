VARYING vec2 vInlandUv;
VARYING vec3 vInlandTint;
void MAIN() {
    vec2 drift = vec2(uTime * 0.0015, uTime * 0.0008);
    vec3 first = texture(waterMap, vInlandUv + drift).rgb;
    vec3 second = texture(waterMap, vInlandUv * 0.5 - drift).rgb;
    vec3 body = mix(vInlandTint, mix(first, second, 0.35), 0.65);
    body *= uWaterTint.rgb;
    float foam = smoothstep(0.55, 0.80, vInlandTint.r)
        * smoothstep(0.78, 0.90, vInlandTint.g);
    float ripple = 0.92 + 0.08 * sin(uTime * 2.0 - vInlandUv.y * 40.0);
    BASE_COLOR = vec4(mix(body, vec3(0.88, 0.96, 0.93) * ripple, foam), 1.0);
    EMISSIVE_COLOR = vec3(0.06, 0.08, 0.08) * foam;
    METALNESS = 0.0;
    ROUGHNESS = 0.68;
    SPECULAR_AMOUNT = 0.12;
}
