// Authored positions stay in model units; only depth is moved to the sky slice.
VARYING vec3 vEngineNormal;
VARYING vec3 vEnginePosition;
VARYING vec4 vEngineColor;
VARYING vec2 vEngineUv;
VARYING vec3 vEnginePointLight;
VARYING float vEngineEyeDepth;
void MAIN() {
    vec3 local = mat3(MODEL_MATRIX)*VERTEX + MODEL_MATRIX[3].xyz-uCameraPosition;
    vEngineNormal = normalize(NORMAL_MATRIX*NORMAL);
    vEnginePosition = uCameraPosition+local;
    vEngineEyeDepth = -(mat3(VIEW_MATRIX)*local).z;
    POSITION = PROJECTION_MATRIX*vec4(mat3(VIEW_MATRIX)*local,1.0);
    POSITION.z = POSITION.w;
    vEngineColor = vec4(1.0);
    vEnginePointLight = vec3(0.0);
    vEngineUv = UV0;
    if (uEnvironmentMap) {
        vec3 p=mat3(VIEW_MATRIX)*local;
        vec3 n=normalize(mat3(VIEW_MATRIX)*vEngineNormal);
        vec3 reflection=p-2.0*dot(p,n)*n;
        vEngineUv=reflection.xy/max(length(reflection),0.000001)*0.5+vec2(0.5);
    }
}
