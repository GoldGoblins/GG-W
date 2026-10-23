// Same swell as game_engine_mobility._surface_components. Steepness stays 0:
// the vertex at this x,z is the height the rider samples. Do not add a
// sideways crest shift here.

VARYING vec3 vWorld;
VARYING float vCrest;
VARYING float vFade;
VARYING float vHeight;

const vec4 GG_WAVE_0 = vec4(0.78, 0.63, 2.80, 0.045);
const vec2 GG_RATE_0 = vec2(0.46, 0.20);
const vec4 GG_WAVE_1 = vec4(-0.35, 0.94, 1.45, 0.085);
const vec2 GG_RATE_1 = vec2(0.78, 1.40);
const vec4 GG_WAVE_2 = vec4(0.96, -0.28, 0.36, 0.105);
const vec2 GG_RATE_2 = vec2(1.05, 2.50);
const vec4 GG_WAVE_3 = vec4(0.42, 0.91, 0.14, 0.145);
const vec2 GG_RATE_3 = vec2(1.45, 0.80);
const float GG_TIDE_AMP = 0.55;
const float GG_TIDE_PERIOD = 110.0;
const float GG_OFFSHORE_START = 48.0;
const float GG_OFFSHORE_SPAN = 100.0;
const float GG_OFFSHORE_FLOOR = 0.15;
const float GG_OFFSHORE_GAIN = 0.85;
const float GG_TAU = 6.283185307179586;

float offshoreScale(vec2 p) {
    float dist = length(p);
    float blend = clamp((dist - GG_OFFSHORE_START) / GG_OFFSHORE_SPAN, 0.0, 1.0);
    blend = blend * blend * (3.0 - 2.0 * blend);
    return GG_OFFSHORE_FLOOR + GG_OFFSHORE_GAIN * blend;
}

void swell(vec4 wave, vec2 rate, vec2 p, float timeValue, float scale,
           inout float height, inout float dhdx, inout float dhdz,
           inout float crestSum, inout float crestWeight) {
    float amplitude = wave.z * scale;
    float phase = wave.w * (wave.x * p.x + wave.y * p.y)
        - rate.x * timeValue + rate.y;
    float sine = sin(phase);
    float cosine = cos(phase);
    height += amplitude * sine;
    float derivative = amplitude * wave.w * cosine;
    dhdx += derivative * wave.x;
    dhdz += derivative * wave.y;
    crestSum += amplitude * max(0.0, sine);
    crestWeight += amplitude;
}

float planetDrop(vec2 p, float height) {
    float radial = max(1.0, uPlanet + height);
    float under = radial * radial - p.x * p.x - p.y * p.y;
    // Equivalent expression without catastrophic float cancellation near
    // the origin of a million-metre planet.
    return height - dot(p, p) / (sqrt(max(1.0, under)) + radial);
}

void MAIN() {
    // The disk sits on the player, so local XZ is not the world point.
    // MODEL_MATRIX is the node's position. A uniform copied from the player
    // can stay at 0 and then the island's clear hole follows them.
    float lip = VERTEX.y;
    vec3 world = (MODEL_MATRIX * vec4(VERTEX.x, 0.0, VERTEX.z, 1.0)).xyz;
    vec2 p = world.xz;
    float scale = offshoreScale(p);
    float tidePhase = uTime * (GG_TAU / GG_TIDE_PERIOD);
    float height = uSea + GG_TIDE_AMP * scale * sin(tidePhase);
    float dhdx = 0.0;
    float dhdz = 0.0;
    float crestSum = 0.0;
    float crestWeight = 0.0;
    swell(GG_WAVE_0, GG_RATE_0, p, uTime, scale, height, dhdx, dhdz, crestSum, crestWeight);
    swell(GG_WAVE_1, GG_RATE_1, p, uTime, scale, height, dhdx, dhdz, crestSum, crestWeight);
    swell(GG_WAVE_2, GG_RATE_2, p, uTime, scale, height, dhdx, dhdz, crestSum, crestWeight);
    swell(GG_WAVE_3, GG_RATE_3, p, uTime, scale, height, dhdx, dhdz, crestSum, crestWeight);
    float crest = crestWeight > 1e-6 ? clamp(crestSum / crestWeight, 0.0, 1.0) : 0.0;
    float curved = planetDrop(p, height);
    VERTEX.y = (curved - uSea) + lip;
    NORMAL = normalize(vec3(-dhdx, 1.0, -dhdz));
    vWorld = vec3(p.x, curved + lip, p.y);
    vCrest = crest;
    vFade = COLOR.r;
    vHeight = height;
    UV0 = p / 40.0;
}
