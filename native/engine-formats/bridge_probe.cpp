#include "gg_engine_formats.h"
#include <cassert>
#include <cstddef>
#include <iostream>
#include <string>

int main(int argc,char **argv) {
    assert(argc==4 && gga_abi_version()==1);
    void *reader=gga_create(argv[1]);assert(reader);
    const std::string query=argv[2];
    assert(gga_request(reader,query.data(),query.size())==0);
    size_t size=0;const char *response=static_cast<const char*>(gga_response(reader,&size));
    const std::string decoded(response,size);
    assert(decoded.find("\"format\":\"BLP2\"")!=std::string::npos);
    assert(decoded.find("\"ok\":true")!=std::string::npos);
    const auto *pixels=static_cast<const unsigned char*>(gga_blob(reader,&size));assert(size==16);
    for(size_t i=0;i<16;i+=4)assert(pixels[i]==240 && pixels[i+1]==176 && pixels[i+2]==36 && pixels[i+3]==255);
    const std::string outside=argv[3];
    assert(gga_request(reader,outside.data(),outside.size())==0);
    response=static_cast<const char*>(gga_response(reader,&size));
    assert(std::string(response,size).find("\"ok\":false")!=std::string::npos);
    gga_blob(reader,&size);assert(size==0);
    gga_destroy(reader);
    std::cout<<"PASS\n";
}
