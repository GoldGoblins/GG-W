VARYING vec3 vPaintPosition;
VARYING vec3 vPaintNormal;
VARYING vec3 vPaintColor;
// BEGIN PAINT MEANS
// Generated from the actual runtime images, not guessed palette values.
vec3 tileMean(int i) {
    if (i == 0) return vec3(0.542364,0.755014,0.116731);
    if (i == 1) return vec3(0.929276,0.665955,0.233976);
    if (i == 2) return vec3(0.608889,0.515973,0.41884);
    if (i == 3) return vec3(0.74519,0.366798,0.233622);
    if (i == 4) return vec3(0.966411,0.849784,0.631017);
    if (i == 5) return vec3(0.640141,0.375634,0.143553);
    if (i == 6) return vec3(0.760595,0.333703,0.202769);
    if (i == 7) return vec3(0.45892,0.452829,0.271647);
    if (i == 8) return vec3(0.581756,0.329044,0.173323);
    if (i == 9) return vec3(0.288289,0.493929,0.187212);
    if (i == 10) return vec3(0.026052,0.240222,0.717404);
    if (i == 11) return vec3(0.609692,0.303039,0.123624);
    if (i == 12) return vec3(0.343971,0.452744,0.584759);
    if (i == 13) return vec3(0.777621,0.865938,0.984843);
    if (i == 14) return vec3(0.017626,0.541937,0.663458);
    if (i == 15) return vec3(0.97898,0.676489,0.480468);
    return vec3(1.0);
}
// END PAINT MEANS

int paintFamily(vec3 c) {
    if (uSurfaceKind == 1) {
        if (c.b > c.g * 1.2 || (c.r > c.g * 1.25 && c.r > 0.6)) return 15;
        if (c.g > c.r * 0.98 && c.g > c.b * 1.3) return 9;
        if (c.r > c.g * 1.1 && c.r > c.b * 1.15) return 8;
        return 7;
    }
    if (uSurfaceKind == 2) {
        if (min(c.r, min(c.g, c.b)) > 0.68) return 13;
        if (c.g > c.r * 1.12) return 0;
        if (c.b > c.r * 1.15) return 14;
        if (c.r > c.g * 1.3 && c.g > c.b * 1.2) return 1;
        return c.r > c.g * 1.15 ? 3 : 7;
    }
    if (uSurfaceKind == 3) {
        if (c.b > c.r * 1.25 || (c.g > c.r * 1.35 && c.b > c.g * 0.7)) return 10;
        if (max(c.r, max(c.g, c.b)) < 0.18) return 11;
        if (max(c.r, max(c.g, c.b)) - min(c.r, min(c.g, c.b)) < 0.07) return 12;
        return 15;
    }
    if (c.g > c.r * 1.08 && c.g > c.b * 1.12) return 9;
    if (c.b > c.r * 1.15 || (c.g > c.r * 1.25 && c.b > c.g * 0.7)) return c.g < 0.3 ? 15 : 6;
    if (c.r > c.g * 2.4) return 6;
    if (c.r > c.g * 1.65) return 5;
    if (c.r > c.g * 1.18 && c.g > c.b * 1.4) return 4;
    return 2;
}
float tileMetres(int i) {
    if (i == 0) return 12.0;
    if (i == 1) return 9.0;
    if (i == 2) return 7.0;
    if (i == 3) return 12.0;
    if (i == 4) return 5.0;
    if (i == 5) return 3.2;
    if (i == 6) return 5.4;
    if (i == 7) return 8.0;
    if (i == 8) return 4.0;
    if (i == 9) return 5.0;
    if (i == 10) return 2.0;
    if (i == 11) return 2.0;
    if (i == 12) return 3.0;
    if (i == 13) return 12.0;
    if (i == 14) return 18.0;
    if (i == 15) return 2.0;
    return 5.0;
}
// BEGIN PAINT STRENGTH
float tileStrength(int i) {
    if (i == 0) return 0.55;
    if (i == 1) return 0.65;
    if (i == 2) return 0.70;
    if (i == 3) return 0.80;
    if (i == 4) return 0.35;
    if (i == 5) return 0.85;
    if (i == 6) return 0.90;
    if (i == 7) return 0.75;
    if (i == 8) return 0.85;
    if (i == 9) return 0.80;
    if (i == 10) return 0.35;
    if (i == 11) return 0.50;
    if (i == 12) return 0.65;
    if (i == 13) return 0.60;
    if (i == 14) return 0.45;
    if (i == 15) return 0.20;
    return 0.5;
}
// END PAINT STRENGTH
vec3 paintedTile(int i, vec2 uv) {
    vec2 cell = vec2(float(i % 4), float(i / 4));
    vec2 at = (cell * 272.0 + 8.0 + fract(uv) * 256.0) / 1088.0;
    // Qt's custom sampler uses bottom-origin UVs; the image sheet is top-origin.
    at.y = 1.0 - at.y;
    // Derivatives of unwrapped UVs avoid a coarse mip/grid at repeat seams.
    float footprint = max(length(dFdx(uv)), length(dFdy(uv))) * 256.0;
    float shrink = min(1.0, 8.0 / max(1.0, footprint));
    vec3 sampleColor = textureGrad(clayAtlas, at,
        dFdx(uv) * vec2(256.0 / 1088.0, -256.0 / 1088.0) * shrink,
        dFdy(uv) * vec2(256.0 / 1088.0, -256.0 / 1088.0) * shrink).rgb;
    // At long range return each material's own average instead of sampling
    // atlas mips which blend neighboring material cells into the wrong hue.
    return mix(sampleColor, tileMean(i), smoothstep(8.0, 24.0, footprint));
}
void MAIN() {
    int family = paintFamily(vPaintColor);
    vec3 p = vPaintPosition / tileMetres(family);
    vec3 normal = abs(normalize(vPaintNormal));
    vec3 image;
    if (uSurfaceKind == 1 || uSurfaceKind == 2) {
        vec3 weights = pow(normal, vec3(4.0));
        weights /= max(0.0001, weights.x + weights.y + weights.z);
        image = paintedTile(family, p.zy) * weights.x
              + paintedTile(family, p.xz) * weights.y
              + paintedTile(family, p.xy) * weights.z;
    } else {
        vec2 uv = normal.y > max(normal.x, normal.z) ? p.xz
                : normal.x > normal.z ? p.zy : p.xy;
        if (family == 6 && normal.y > 0.3) uv = vec2(p.z, -abs(p.x));
        image = paintedTile(family, uv);
    }
    vec3 tint = pow(max(vPaintColor, vec3(0.0)), vec3(1.0 / 2.2));
    vec3 brush = clamp(image / max(tileMean(family), vec3(0.05)), vec3(0.38), vec3(1.65));
    brush = mix(vec3(1.0), brush, tileStrength(family));
    BASE_COLOR = vec4(clamp(tint * brush * 0.96, 0.0, 1.0), 1.0);
    if (uLampEmission > 0.5 && vPaintColor.r > 0.8 && vPaintColor.g > 0.5 && vPaintColor.b < 0.3)
        EMISSIVE_COLOR = vec3(2.0, 0.72, 0.14);
    METALNESS = 0.0;
    ROUGHNESS = 0.96;
    SPECULAR_AMOUNT = 0.08;
}
