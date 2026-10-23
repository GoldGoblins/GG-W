VARYING vec4 vFxColor;
VARYING vec2 vFxUV;
VARYING float vFxDistance;
VARYING float vFxBeacon;
void MAIN() {
    vec2 point = vFxUV * 2.0 - 1.0;
    float ripple = sin(point.x * 6.0 + uTime * .7)
        * sin(point.y * 5.0 - uTime * .45) * .065;
    float cloud = 1.0 - smoothstep(.1, 1.0, length(point) + ripple);
    // CPU particle colours are sRGB; HDR blending happens in linear light.
    // Unshaded/additive effects do not receive Qt's material fog. Fade their
    // energy too, so distant lamps and mist cannot shine through the cutoff.
    float visibility = 1.0 - smoothstep(uFogNear,uFogFar,vFxDistance);
    // Fog weakens the tiny light core, while its final range fades separately.
    // Starting that final fade at ordinary fog-near erased distant beacons.
    float beaconVisibility=mix(1.0,.45,smoothstep(uFogNear,uFogFar,vFxDistance))
        *(1.0-smoothstep(uBeaconFar*.9,uBeaconFar,vFxDistance));
    visibility=mix(visibility,beaconVisibility,vFxBeacon);
    FRAGCOLOR = vec4(pow(vFxColor.rgb, vec3(2.2)) * uEnergy,
                    vFxColor.a * cloud * visibility);
}
