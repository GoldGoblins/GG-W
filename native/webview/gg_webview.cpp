// GG's small Windows WebView2 host. All COM calls stay on Qt's GUI thread.
// Browser/extension code comes from Microsoft and the original extension author.
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <wrl.h>
#include <algorithm>
#include <cstdint>
#include <deque>
#include <map>
#include <memory>
#include <string>
#include "WebView2.h"
#include "WebView2EnvironmentOptions.h"

using Microsoft::WRL::Callback;
using Microsoft::WRL::ComPtr;
using Microsoft::WRL::Make;
using Handle = std::uint64_t;
constexpr size_t MaxEventBytes = 2 * 1024 * 1024;
constexpr size_t MaxQueueBytes = 4 * 1024 * 1024;

static std::string utf8(const std::wstring &text) {
    if (text.empty()) return {};
    int size = WideCharToMultiByte(CP_UTF8, 0, text.data(), int(text.size()), nullptr, 0, nullptr, nullptr);
    std::string result(size, '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), int(text.size()), result.data(), size, nullptr, nullptr);
    return result;
}
static std::string quote(const std::wstring &value) {
    std::string result = "\"";
    for (unsigned char c : utf8(value)) {
        switch (c) {
        case '"': result += "\\\""; break;
        case '\\': result += "\\\\"; break;
        case '\n': result += "\\n"; break;
        case '\r': result += "\\r"; break;
        case '\t': result += "\\t"; break;
        default:
            if (c < 32) {
                const char hex[] = "0123456789abcdef";
                result += "\\u00"; result += hex[c >> 4]; result += hex[c & 15];
            } else result += char(c);
        }
    }
    return result + '"';
}
struct View {
    HWND child = nullptr;
    DWORD thread = GetCurrentThreadId();
    bool closed = false, visible = false;
    RECT bounds{0, 0, 1, 1};
    std::wstring extensionId;
    ComPtr<ICoreWebView2Environment> environment;
    ComPtr<ICoreWebView2Controller> controller;
    ComPtr<ICoreWebView2> browser;
    std::deque<std::string> events;
    size_t queueBytes = 0;
    void emit(std::string event) {
        if (closed || event.size() > MaxEventBytes) return;
        // Never silently drop a JavaScript callback and leave its caller stuck.
        if (queueBytes + event.size() > MaxQueueBytes) {
            events.clear(); queueBytes = 0;
            event = "{\"type\":\"fatal\",\"message\":\"Browser event queue exceeded its limit\"}";
        }
        queueBytes += event.size(); events.push_back(std::move(event));
    }
    void error(const char *stage, HRESULT hr) {
        emit("{\"type\":\"error\",\"stage\":\"" + std::string(stage) + "\",\"code\":"
             + std::to_string(static_cast<std::uint32_t>(hr)) + "}");
    }
    bool allowed(const std::wstring &url) const {
        const auto extensionPrefix = L"chrome-extension://" + extensionId + L"/";
        return url == L"about:blank" || url.compare(0, 7, L"http://") == 0
            || url.compare(0, 8, L"https://") == 0
            || (!extensionId.empty() && url.compare(0, extensionPrefix.size(), extensionPrefix) == 0);
    }
};
static std::map<Handle, std::shared_ptr<View>> views;
static Handle nextHandle = 1;
static std::shared_ptr<View> get(Handle handle) {
    auto it = views.find(handle);
    return it == views.end() || it->second->closed || it->second->thread != GetCurrentThreadId()
        ? nullptr : it->second;
}
static void source(const std::shared_ptr<View> &v) {
    LPWSTR url = nullptr;
    if (SUCCEEDED(v->browser->get_Source(&url))) {
        v->emit("{\"type\":\"url\",\"url\":" + quote(url ? url : L"") + "}");
    }
    CoTaskMemFree(url);
    BOOL back = FALSE, forward = FALSE;
    v->browser->get_CanGoBack(&back); v->browser->get_CanGoForward(&forward);
    v->emit(std::string("{\"type\":\"history\",\"back\":") + (back ? "true" : "false")
            + ",\"forward\":" + (forward ? "true" : "false") + "}");
}

static void hook(const std::shared_ptr<View> &v) {
    const std::weak_ptr<View> weak = v;
    EventRegistrationToken token{};
    v->browser->add_NavigationStarting(Callback<ICoreWebView2NavigationStartingEventHandler>(
        [weak](ICoreWebView2 *, ICoreWebView2NavigationStartingEventArgs *args) -> HRESULT {
            auto v = weak.lock(); if (!v || v->closed) return S_OK;
            LPWSTR raw = nullptr; args->get_Uri(&raw);
            std::wstring url(raw ? raw : L""); CoTaskMemFree(raw);
            if (!v->allowed(url)) {
                args->put_Cancel(TRUE);
                v->emit("{\"type\":\"blocked\"}");
            } else v->emit("{\"type\":\"load\",\"status\":0,\"url\":" + quote(url) + "}");
            return S_OK;
        }).Get(), &token);
    v->browser->add_NavigationCompleted(Callback<ICoreWebView2NavigationCompletedEventHandler>(
        [weak](ICoreWebView2 *, ICoreWebView2NavigationCompletedEventArgs *args) -> HRESULT {
            auto v = weak.lock(); if (!v || v->closed) return S_OK;
            BOOL success = FALSE; args->get_IsSuccess(&success);
            COREWEBVIEW2_WEB_ERROR_STATUS error{}; args->get_WebErrorStatus(&error);
            source(v);
            v->emit("{\"type\":\"load\",\"status\":" + std::to_string(success ? 2 : 3)
                    + ",\"error\":" + std::to_string(error) + "}");
            return S_OK;
        }).Get(), &token);
    v->browser->add_SourceChanged(Callback<ICoreWebView2SourceChangedEventHandler>(
        [weak](ICoreWebView2 *, ICoreWebView2SourceChangedEventArgs *) -> HRESULT {
            auto v = weak.lock(); if (v && !v->closed) source(v); return S_OK;
        }).Get(), &token);
    v->browser->add_HistoryChanged(Callback<ICoreWebView2HistoryChangedEventHandler>(
        [weak](ICoreWebView2 *, IUnknown *) -> HRESULT {
            auto v = weak.lock(); if (v && !v->closed) source(v); return S_OK;
        }).Get(), &token);
    v->browser->add_DocumentTitleChanged(Callback<ICoreWebView2DocumentTitleChangedEventHandler>(
        [weak](ICoreWebView2 *, IUnknown *) -> HRESULT {
            auto v = weak.lock(); if (!v || v->closed) return S_OK;
            LPWSTR title = nullptr; v->browser->get_DocumentTitle(&title);
            v->emit("{\"type\":\"title\",\"title\":" + quote(title ? title : L"") + "}");
            CoTaskMemFree(title); return S_OK;
        }).Get(), &token);
    v->browser->add_NewWindowRequested(Callback<ICoreWebView2NewWindowRequestedEventHandler>(
        [weak](ICoreWebView2 *, ICoreWebView2NewWindowRequestedEventArgs *args) -> HRESULT {
            args->put_Handled(TRUE);
            auto v = weak.lock(); if (!v || v->closed) return S_OK;
            LPWSTR raw = nullptr; args->get_Uri(&raw);
            std::wstring url(raw ? raw : L""); CoTaskMemFree(raw);
            if (v->allowed(url)) v->emit("{\"type\":\"newtab\",\"url\":" + quote(url) + "}");
            return S_OK;
        }).Get(), &token);
    v->browser->add_ProcessFailed(Callback<ICoreWebView2ProcessFailedEventHandler>(
        [weak](ICoreWebView2 *, ICoreWebView2ProcessFailedEventArgs *) -> HRESULT {
            auto v = weak.lock(); if (v && !v->closed) v->emit("{\"type\":\"fatal\",\"message\":\"Browser process stopped\"}");
            return S_OK;
        }).Get(), &token);
}

struct ExtensionState {
    bool ready = false, installing = false;
    HRESULT error = S_OK;
    std::wstring id;
    std::deque<std::weak_ptr<View>> waiting;
};
static std::map<std::wstring, ExtensionState> extensions;
static void extensionReady(const std::wstring &key, HRESULT hr, ICoreWebView2BrowserExtension *extension) {
    auto &state = extensions[key];
    state.installing = false; state.error = hr;
    if (SUCCEEDED(hr) && extension) {
        LPWSTR id = nullptr; extension->get_Id(&id);
        state.id = id ? id : L""; CoTaskMemFree(id); state.ready = !state.id.empty();
    }
    while (!state.waiting.empty()) {
        auto v = state.waiting.front().lock(); state.waiting.pop_front();
        if (!v || v->closed) continue;
        if (state.ready) {
            v->extensionId = state.id;
            v->emit("{\"type\":\"ready\",\"extensionId\":" + quote(state.id) + "}");
        } else v->error("extension", FAILED(hr) ? hr : E_FAIL);
    }
}
static void installExtension(const std::shared_ptr<View> &v, const std::wstring &profile,
                             const std::wstring &directory) {
    const std::wstring key = profile + L"\n" + directory;
    auto &state = extensions[key];
    if (state.ready) {
        v->extensionId = state.id;
        v->emit("{\"type\":\"ready\",\"extensionId\":" + quote(state.id) + "}"); return;
    }
    state.waiting.push_back(v);
    if (state.installing) return;
    state.installing = true;
    ComPtr<ICoreWebView2_13> browser13;
    ComPtr<ICoreWebView2Profile> browserProfile;
    ComPtr<ICoreWebView2Profile7> profile7;
    HRESULT hr = v->browser.As(&browser13);
    if (SUCCEEDED(hr)) hr = browser13->get_Profile(&browserProfile);
    if (SUCCEEDED(hr)) hr = browserProfile.As(&profile7);
    if (FAILED(hr)) { extensionReady(key, hr, nullptr); return; }
    hr = profile7->AddBrowserExtension(directory.c_str(),
        Callback<ICoreWebView2ProfileAddBrowserExtensionCompletedHandler>(
            [key](HRESULT hr, ICoreWebView2BrowserExtension *extension) -> HRESULT {
                extensionReady(key, hr, extension); return S_OK;
            }).Get());
    if (FAILED(hr)) extensionReady(key, hr, nullptr);
}

#define API extern "C" __declspec(dllexport)
API Handle __cdecl ggwv_create(std::uint64_t parent, const wchar_t *profile,
                               const wchar_t *extensionDirectory) {
    if (!parent || !profile || !extensionDirectory) return 0;
    auto v = std::make_shared<View>();
    v->child = CreateWindowExW(0, L"STATIC", L"GG WEB", WS_CHILD | WS_CLIPCHILDREN | WS_CLIPSIBLINGS,
                               0, 0, 1, 1, reinterpret_cast<HWND>(parent), nullptr, GetModuleHandleW(nullptr), nullptr);
    if (!v->child) return 0;
    const Handle handle = nextHandle++;
    views[handle] = v;
    const std::weak_ptr<View> weak = v;
    const std::wstring profilePath(profile), extensionPath(extensionDirectory);
    auto options = Make<CoreWebView2EnvironmentOptions>();
    ComPtr<ICoreWebView2EnvironmentOptions6> options6;
    HRESULT hr = options.As(&options6);
    if (SUCCEEDED(hr)) hr = options6->put_AreBrowserExtensionsEnabled(TRUE);
    // Development fixtures can override arguments through WebView2's documented
    // environment variable. Production does not add flags or open debug ports.
    if (FAILED(hr)) { v->error("options", hr); return handle; }
    hr = CreateCoreWebView2EnvironmentWithOptions(nullptr, profilePath.c_str(), options.Get(),
        Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
            [weak, profilePath, extensionPath](HRESULT hr, ICoreWebView2Environment *environment) -> HRESULT {
                auto v = weak.lock(); if (!v || v->closed) return S_OK;
                if (FAILED(hr) || !environment) { v->error("environment", hr); return S_OK; }
                v->environment = environment;
                hr = environment->CreateCoreWebView2Controller(v->child,
                    Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                        [weak, profilePath, extensionPath](HRESULT hr, ICoreWebView2Controller *controller) -> HRESULT {
                            auto v = weak.lock();
                            if (!v || v->closed) { if (controller) controller->Close(); return S_OK; }
                            if (FAILED(hr) || !controller) { v->error("controller", hr); return S_OK; }
                            v->controller = controller;
                            hr = controller->get_CoreWebView2(&v->browser);
                            if (FAILED(hr)) { v->error("browser", hr); return S_OK; }
                            RECT area{0, 0, v->bounds.right, v->bounds.bottom};
                            controller->put_Bounds(area); controller->put_IsVisible(v->visible);
                            ComPtr<ICoreWebView2Settings> settings;
                            if (SUCCEEDED(v->browser->get_Settings(&settings))) settings->put_AreHostObjectsAllowed(FALSE);
                            hook(v);
                            installExtension(v, profilePath, extensionPath);
                            return S_OK;
                        }).Get());
                if (FAILED(hr)) v->error("create_controller", hr);
                return S_OK;
            }).Get());
    if (FAILED(hr)) v->error("create_environment", hr);
    return handle;
}
API void __cdecl ggwv_destroy(Handle handle) {
    auto v = get(handle); if (!v) return;
    v->closed = true;
    if (v->controller) v->controller->Close();
    if (v->child) DestroyWindow(v->child);
    views.erase(handle);
    if (views.empty()) extensions.clear();
}
API void __cdecl ggwv_bounds(Handle handle, int x, int y, int width, int height) {
    auto v = get(handle); if (!v) return;
    width = std::clamp(width, 1, 32768); height = std::clamp(height, 1, 32768);
    v->bounds = {0, 0, width, height};
    SetWindowPos(v->child, HWND_TOP, x, y, width, height, SWP_NOACTIVATE);
    if (v->controller) {
        v->controller->put_Bounds(v->bounds);
        v->controller->NotifyParentWindowPositionChanged();
    }
}
API void __cdecl ggwv_show(Handle handle, int visible) {
    auto v = get(handle); if (!v) return;
    v->visible = visible != 0;
    ShowWindow(v->child, v->visible ? SW_SHOWNOACTIVATE : SW_HIDE);
    if (v->controller) v->controller->put_IsVisible(v->visible);
}
API int __cdecl ggwv_navigate(Handle handle, const wchar_t *url) {
    auto v = get(handle); if (!v || !v->browser || !url || !v->allowed(url)) return 0;
    return SUCCEEDED(v->browser->Navigate(url));
}
API int __cdecl ggwv_command(Handle handle, int command) {
    auto v = get(handle); if (!v || !v->browser) return 0;
    HRESULT hr = E_INVALIDARG;
    if (command == 0) hr = v->browser->GoBack();
    if (command == 1) hr = v->browser->GoForward();
    if (command == 2) hr = v->browser->Reload();
    if (command == 3) hr = v->browser->Stop();
    return SUCCEEDED(hr);
}
API int __cdecl ggwv_eval(Handle handle, std::uint64_t request, const wchar_t *script) {
    auto v = get(handle); if (!v || !v->browser || !script || wcslen(script) > 1024 * 1024) return 0;
    const std::weak_ptr<View> weak = v;
    HRESULT hr = v->browser->ExecuteScript(script,
        Callback<ICoreWebView2ExecuteScriptCompletedHandler>(
            [weak, request](HRESULT hr, LPCWSTR result) -> HRESULT {
                auto v = weak.lock(); if (!v || v->closed) return S_OK;
                std::string json = result ? utf8(result) : "null";
                if (json.empty()) json = "null";
                if (json.size() > MaxEventBytes - 256) { json = "null"; hr = E_BOUNDS; }
                v->emit("{\"type\":\"script\",\"request\":" + std::to_string(request)
                        + ",\"ok\":" + (SUCCEEDED(hr) ? "true" : "false") + ",\"result\":" + json + "}");
                return S_OK;
            }).Get());
    return SUCCEEDED(hr);
}
// Trusted application diagnostics only; no network listener or page host object.
API int __cdecl ggwv_devtools(Handle handle, std::uint64_t request, const wchar_t *method,
                              const wchar_t *parameters, const wchar_t *session) {
    auto v = get(handle); if (!v || !v->browser || !method || !parameters) return 0;
    const std::weak_ptr<View> weak = v;
    auto callback = Callback<ICoreWebView2CallDevToolsProtocolMethodCompletedHandler>(
        [weak, request](HRESULT hr, LPCWSTR result) -> HRESULT {
            auto v = weak.lock(); if (!v || v->closed) return S_OK;
            std::string json = result ? utf8(result) : "null";
            if (json.empty()) json = "null";
            if (json.size() > MaxEventBytes - 256) { json = "null"; hr = E_BOUNDS; }
            v->emit("{\"type\":\"devtools\",\"request\":" + std::to_string(request)
                    + ",\"ok\":" + (SUCCEEDED(hr) ? "true" : "false") + ",\"result\":" + json + "}");
            return S_OK;
        });
    if (session && *session) {
        ComPtr<ICoreWebView2_11> browser11;
        if (FAILED(v->browser.As(&browser11))) return 0;
        return SUCCEEDED(browser11->CallDevToolsProtocolMethodForSession(session, method, parameters, callback.Get()));
    }
    return SUCCEEDED(v->browser->CallDevToolsProtocolMethod(method, parameters, callback.Get()));
}
API unsigned __cdecl ggwv_poll(Handle handle, char *buffer, unsigned capacity) {
    auto v = get(handle); if (!v || v->events.empty()) return 0;
    const auto &event = v->events.front();
    const unsigned required = unsigned(event.size() + 1);
    if (!buffer || capacity < required) return required;
    memcpy(buffer, event.c_str(), required);
    v->queueBytes -= event.size(); v->events.pop_front();
    return required;
}
