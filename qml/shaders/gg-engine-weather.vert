VARYING vec2 vWeatherUv;
VARYING vec4 vWeatherColor;
VARYING float vWeatherDepth;
void MAIN() {
    // The native table is relative to the sampled eye. Keep the Model at the
    // scene origin and use the sampled eye explicitly. Subtract the live eye
    // before projection, preserving small flakes far
    // from the map origin and motion while the next native frame is loading.
    vec3 relative=(INSTANCE_MODEL_MATRIX*vec4(VERTEX,1.0)).xyz;
    vec3 view=mat3(VIEW_MATRIX)*(relative+(uCameraAnchor-CAMERA_POSITION));
    vWeatherDepth=-view.z;
    vWeatherColor=INSTANCE_COLOR;
    if (uLayer==4) {
        // Preserve original per-corner mist alpha before raster interpolation.
        float bottom=mix(INSTANCE_DATA.x,INSTANCE_DATA.y,UV0.x);
        float top=mix(INSTANCE_DATA.w,INSTANCE_DATA.z,UV0.x);
        vWeatherColor.a*=mix(top,bottom,UV0.y);
        vWeatherUv=UV0;
    } else vWeatherUv=UV0*INSTANCE_DATA.zw+INSTANCE_DATA.xy;
    POSITION=PROJECTION_MATRIX*vec4(view,1.0);
}
