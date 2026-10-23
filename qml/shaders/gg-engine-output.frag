// Preserve the RGB blend laws when Qt embeds the opaque game viewport in its UI.
void MAIN() { FRAGCOLOR = vec4(texture(INPUT, INPUT_UV).rgb, 1.0); }
