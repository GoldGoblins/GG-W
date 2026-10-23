// Original Gauss4 offsets and 1/8,3/8,3/8,1/8 weights.
void MAIN() {
    vec2 t=(filterAxis<.5 ? vec2(1,0) : vec2(0,1))/INPUT_SIZE;
    FRAGCOLOR=.125*texture(INPUT,INPUT_UV-2.5*t)+.375*texture(INPUT,INPUT_UV-.5*t)
        +.375*texture(INPUT,INPUT_UV+.5*t)+.125*texture(INPUT,INPUT_UV+2.5*t);
}
