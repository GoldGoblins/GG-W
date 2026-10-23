#include "crates/gg-engine-client/gg_engine_client.h"
#include <cassert>
#include <iostream>
#include <string>

int main() {
    assert(ggc_abi_version()==1);
    void *client=ggc_create();assert(client);
    auto request=[&](const std::string &json) {
        assert(ggc_request(client,reinterpret_cast<const uint8_t*>(json.data()),json.size())==0);
        size_t length=0;const auto *data=ggc_response(client,&length);
        assert(data && length<8*1024*1024);return std::string(reinterpret_cast<const char*>(data),length);
    };
    auto catalog=request(R"({"op":"catalog"})");
    assert(catalog.find("\"types\":166")!=std::string::npos);
    assert(catalog.find("\"repair_item\"")!=std::string::npos);
    auto packet=request(R"({"op":"preview_command","command":"set_active_mover","guid":"18446744073709551615"})");
    assert(packet.find("[255,255,255,255,255,255,255,255]")!=std::string::npos);
    assert(request(R"({"op":"unknown"})").find("\"ok\":false")!=std::string::npos);
    const uint8_t dummy=0;assert(ggc_request(client,&dummy,65537)==-1);
    assert(ggc_request(nullptr,&dummy,1)==-1);
    ggc_destroy(client);ggc_destroy(nullptr);std::cout<<"PASS\n";
}
