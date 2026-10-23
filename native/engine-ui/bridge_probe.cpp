#include "gg_engine_ui.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static size_t measure(void *, const void *, size_t, void *output, size_t capacity) {
    const char result[] = "[8,12,8]";
    if (capacity < sizeof(result)-1) return 0;
    memcpy(output,result,sizeof(result)-1);
    return sizeof(result)-1;
}
static void request(void *handle, const char *json) {
    assert(ggbu_request(handle,json,strlen(json))==0);
    size_t bytes=0;
    const char *answer=static_cast<const char *>(ggbu_response(handle,&bytes));
    assert(answer && bytes>0 && bytes<=16*1024*1024);
    // The transport's JSON encoder writes the leading status first.
    assert(bytes>10 && memcmp(answer,"{\"ok\":true",10)==0);
}
int main() {
    assert(ggbu_abi_version()==1);
    void *handle=ggbu_create(); assert(handle);
    assert(ggbu_text_measurer(handle,measure,nullptr)==0);
    request(handle,R"GG({"op":"snapshot","health":73,"resource":11})GG");
    request(handle,R"GG({"op":"exec","source":"T=UIParent:CreateFontString('T') T:SetFont('Sans Serif',12) T:SetText('C++ callback')"})GG");
    request(handle,R"GG({"op":"eval","source":"return type(CreateFrame),UnitHealth('player'),UnitMana('player'),T:GetStringWidth()"})GG");
    size_t bytes=0; const void *answer=ggbu_response(handle,&bytes);
    assert(fwrite(answer,1,bytes,stdout)==bytes);putchar('\n');
    ggbu_destroy(handle);
}
