VARYING vec2 vStarUv;
void MAIN() { float a=texture(uTexture,vStarUv).a*uAlpha;FRAGCOLOR=vec4(vec3(a),a); }
