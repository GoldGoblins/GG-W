// Painted tile at world XZ, and the same clarity curve as water_clarity().
// Open sea remains translucent. Land under the disk is not painted.

VARYING vec3 vWorld;
VARYING float vCrest;
VARYING float vFade;
VARYING float vHeight;

const float GG_TILE = 40.0;
const float GG_LAND_DEPTH = 0.12;
const float GG_SIGHT = 5.5;
const float GG_CLARITY_CLEAR = 0.28;
const float GG_CLARITY_SPAN = 0.44;
const float GG_BED_MIN = -80.0;
const float GG_BED_SPAN = 120.0;

float waterClarity(float depth) {
    if (depth <= GG_LAND_DEPTH)
        return 0.0;
    float span = clamp((depth - GG_LAND_DEPTH) / GG_SIGHT, 0.0, 1.0);
    span = span * span * (3.0 - 2.0 * span);
    return GG_CLARITY_CLEAR + GG_CLARITY_SPAN * span;
}

void MAIN() {
    vec2 uv = vWorld.xz / GG_TILE;
    vec4 tex = texture(seaMap, uv);
    float face = vCrest * vCrest * (3.0 - 2.0 * vCrest);
    float mask = 0.90 + 0.10 * face;
    mask = mix(mask, 1.0, vFade);
    vec3 rgb = tex.rgb * mask;
    rgb *= uWaterTint.rgb;
    rgb = mix(rgb, rgb * vec3(0.94, 1.0, 1.08), vFade);
    vec2 raw = (vWorld.xz + vec2(uBedExtent)) / (2.0 * uBedExtent);
    float inside = step(0.0, raw.x) * step(raw.x, 1.0)
        * step(0.0, raw.y) * step(raw.y, 1.0);
    // A missing sample stays deep, so a bad texture cannot blank the ocean.
    float encoded = texture(seaBed, clamp(raw, 0.0, 1.0)).r;
    float terrainY = mix(-48.0, encoded * GG_BED_SPAN + GG_BED_MIN, inside);
    float alpha = waterClarity(vHeight - terrainY);
    BASE_COLOR = vec4(rgb, alpha);
    METALNESS = 0.0;
    ROUGHNESS = 0.78;
    SPECULAR_AMOUNT = 0.08;
}
