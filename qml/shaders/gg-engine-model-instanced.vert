// Instanced counterpart of gg-engine-model.vert, using Qt public instance matrices.
VARYING vec3 vEngineNormal;
VARYING vec3 vEnginePosition;
VARYING vec4 vEngineColor;
VARYING vec2 vEngineUv;
VARYING vec3 vEnginePointLight;
VARYING float vEngineEyeDepth;
vec3 engineNormal(vec3 value) {
    return dot(value,value) > 1e-12 ? normalize(value) : vec3(0.0);
}
void MAIN() {
    mat3 normalTransform = transpose(inverse(mat3(uModelSpaceLight ? inverse(MODEL_MATRIX)*INSTANCE_MODEL_MATRIX : INSTANCE_MODEL_MATRIX)));
    vEngineNormal = engineNormal(normalTransform * NORMAL);
    vEnginePosition = (INSTANCE_MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
    vEngineEyeDepth = -(VIEW_MATRIX * vec4(vEnginePosition,1.0)).z;
    POSITION = VIEWPROJECTION_MATRIX * vec4(vEnginePosition, 1.0);
    vEngineColor = (uVertexColors ? COLOR : vec4(1.0)) * INSTANCE_COLOR;
    vEngineUv = UV0;
    if (uEnvironmentMap) {
        vec3 p = (VIEW_MATRIX * vec4(vEnginePosition,1.0)).xyz;
        vec3 n = engineNormal((VIEW_MATRIX * vec4(engineNormal(transpose(inverse(mat3(INSTANCE_MODEL_MATRIX))) * NORMAL),0.0)).xyz);
        vec3 reflection = p - 2.0*dot(p,n)*n;
        reflection /= max(length(reflection),0.000001);
        vEngineUv = reflection.xy*0.5 + vec2(0.5);
    }
    vec3 lightVector = uLightPosition - (uModelSpaceLight ? (inverse(MODEL_MATRIX)*vec4(vEnginePosition,1.0)).xyz : vEnginePosition);
    float d = length(lightVector);
    float falloff = 1.0 / max(0.000001,0.7*d + 0.03*d*d);
    vEnginePointLight = uPointLight ? uDiffuse * falloff * max(0.0,dot(vEngineNormal,lightVector/max(d,0.000001))) : vec3(0.0);
}
