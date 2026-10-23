// Application-only Windows audio: session gain and process-tree loopback.
// Never opens the microphone or changes an endpoint/system master volume.
#define NOMINMAX
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <tlhelp32.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <audiopolicy.h>
#include <wrl.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <vector>

using Microsoft::WRL::ComPtr;
using Microsoft::WRL::RuntimeClass;
using Microsoft::WRL::RuntimeClassFlags;
using Microsoft::WRL::ClassicCom;
using Microsoft::WRL::FtmBase;
constexpr unsigned Frames = 4096;
constexpr unsigned Rate = 48000;

struct Activation final : RuntimeClass<RuntimeClassFlags<ClassicCom>,
                                      FtmBase, IActivateAudioInterfaceCompletionHandler> {
    HANDLE done = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    HRESULT result = E_PENDING;
    ComPtr<IAudioClient> client;
    AUDIOCLIENT_ACTIVATION_PARAMS params{};
    PROPVARIANT arguments{};
    ~Activation() { if (done) CloseHandle(done); }
    HRESULT STDMETHODCALLTYPE ActivateCompleted(IActivateAudioInterfaceAsyncOperation* operation) override {
        ComPtr<IUnknown> object;
        HRESULT activated = E_FAIL;
        result = operation->GetActivateResult(&activated, &object);
        if (SUCCEEDED(result)) result = activated;
        if (SUCCEEDED(result)) result = object.As(&client);
        SetEvent(done);
        return S_OK;
    }
};

static std::set<DWORD> process_tree(DWORD root) {
    std::vector<std::pair<DWORD, DWORD>> parents;
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot != INVALID_HANDLE_VALUE) {
        PROCESSENTRY32W entry{}; entry.dwSize = sizeof(entry);
        if (Process32FirstW(snapshot, &entry)) do {
            parents.emplace_back(entry.th32ProcessID, entry.th32ParentProcessID);
        } while (Process32NextW(snapshot, &entry));
        CloseHandle(snapshot);
    }
    std::set<DWORD> owned{root};
    auto born = [](DWORD pid) -> std::uint64_t {
        HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
        FILETIME start{}, exit{}, kernel{}, user{};
        const bool ok = process && GetProcessTimes(process, &start, &exit, &kernel, &user);
        if (process) CloseHandle(process);
        return ok ? (std::uint64_t(start.dwHighDateTime) << 32) | start.dwLowDateTime : 0;
    };
    // Depth/count limits also bound unusual process hierarchies.
    for (unsigned depth = 0; depth < 32 && owned.size() < 1024; ++depth) {
        const auto before = owned.size();
        for (const auto& row : parents) {
            if (owned.count(row.second) && owned.size() < 1024 && !owned.count(row.first)) {
                const auto parent_start = born(row.second), child_start = born(row.first);
                if (parent_start && child_start >= parent_start) owned.insert(row.first);
            }
        }
        if (owned.size() == before) break;
    }
    return owned;
}

struct Session {
    ComPtr<ISimpleAudioVolume> volume;
    float original = 1, applied = -1;
};

struct Bus {
    DWORD pid;
    bool control;
    HANDLE stop = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    HANDLE samples = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    HANDLE changed = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    std::thread worker;
    std::atomic<float> gain{1};
    std::atomic<unsigned> state{0};  // bit 0: session control, bit 1: PCM capture
    std::atomic<unsigned> error{0};
    std::atomic<unsigned> sessions{0};
    std::atomic<float> observed_gain{-1};
    std::mutex mutex;
    std::mutex renderer_mutex;
    std::vector<unsigned> renderers;
    std::array<float, Frames * 2> pcm{};
    unsigned count = 0;
    std::uint64_t sequence = 0, stamp = 0;

    explicit Bus(DWORD root, float level, bool manage = true) : pid(root), control(manage), gain(level) {}
    ~Bus() {
        SetEvent(stop);
        if (worker.joinable()) worker.join();
        CloseHandle(changed); CloseHandle(samples); CloseHandle(stop);
    }

    void update_sessions(IMMDeviceEnumerator* enumerator, std::map<std::wstring, Session>& held) {
        for (auto it = held.begin(); it != held.end();) {
            ComPtr<IAudioSessionControl> control;
            AudioSessionState status = AudioSessionStateExpired;
            if (FAILED(it->second.volume.As(&control)) || FAILED(control->GetState(&status))
                || status == AudioSessionStateExpired) it = held.erase(it);
            else ++it;
        }
        const auto owned = process_tree(pid);
        ComPtr<IMMDeviceCollection> devices;
        if (FAILED(enumerator->EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE, &devices))) return;
        UINT device_count = 0; devices->GetCount(&device_count);
        unsigned matched = 0;
        std::set<unsigned> active_renderers;
        for (UINT d = 0; d < std::min(device_count, 32u); ++d) {
            ComPtr<IMMDevice> device; ComPtr<IAudioSessionManager2> manager;
            if (FAILED(devices->Item(d, &device)) || FAILED(device->Activate(
                __uuidof(IAudioSessionManager2), CLSCTX_ALL, nullptr, &manager))) continue;
            ComPtr<IAudioSessionEnumerator> entries;
            if (FAILED(manager->GetSessionEnumerator(&entries))) continue;
            int size = 0; entries->GetCount(&size);
            for (int i = 0; i < std::min(size, 512); ++i) {
                ComPtr<IAudioSessionControl> base; ComPtr<IAudioSessionControl2> session;
                DWORD process = 0;
                if (FAILED(entries->GetSession(i, &base)) || FAILED(base.As(&session))
                    || session->GetProcessId(&process) != S_OK || !owned.count(process)
                    || session->IsSystemSoundsSession() == S_OK) continue;
                LPWSTR name = nullptr;
                if (FAILED(session->GetSessionInstanceIdentifier(&name))) continue;
                const std::wstring key(name); CoTaskMemFree(name);
                auto found = held.find(key);
                if (found == held.end()) {
                    if (held.size() >= 256) continue;
                    Session row;
                    if (FAILED(session.As(&row.volume)) || FAILED(row.volume->GetMasterVolume(&row.original))) continue;
                    found = held.emplace(key, std::move(row)).first;
                }
                const float level = gain.load();
                float current = -1;
                found->second.volume->GetMasterVolume(&current);
                if (std::abs(current - level) > .0001f)
                    found->second.volume->SetMasterVolume(level, nullptr);
                if (SUCCEEDED(found->second.volume->GetMasterVolume(&current))) observed_gain = current;
                found->second.applied = level;
                AudioSessionState playback = AudioSessionStateInactive;
                if (SUCCEEDED(session->GetState(&playback)) && playback == AudioSessionStateActive
                    && active_renderers.size() < 16) active_renderers.insert(process);
                ++matched;
            }
        }
        sessions = matched;
        {
            std::lock_guard<std::mutex> lock(renderer_mutex);
            renderers.assign(active_renderers.begin(), active_renderers.end());
        }
    }

    HRESULT activate(ComPtr<IAudioClient>& client) {
        auto callback = Microsoft::WRL::Make<Activation>();
        if (!callback || !callback->done) return E_OUTOFMEMORY;
        // The callback owns these arguments even if activation outlives the
        // startup deadline; no asynchronous operation retains stack pointers.
        callback->params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
        callback->params.ProcessLoopbackParams.TargetProcessId = pid;
        callback->params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;
        callback->arguments.vt = VT_BLOB;
        callback->arguments.blob.cbSize = sizeof(callback->params);
        callback->arguments.blob.pBlobData = reinterpret_cast<BYTE*>(&callback->params);
        ComPtr<IActivateAudioInterfaceAsyncOperation> operation;
        HRESULT hr = ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
            __uuidof(IAudioClient), &callback->arguments, callback.Get(), &operation);
        if (FAILED(hr)) return hr;
        HANDLE events[]{stop, callback->done};
        if (WaitForMultipleObjects(2, events, FALSE, 3000) != WAIT_OBJECT_0 + 1)
            return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
        if (FAILED(callback->result)) return callback->result;
        client = callback->client;
        WAVEFORMATEX format{};
        format.wFormatTag = WAVE_FORMAT_IEEE_FLOAT;
        format.nChannels = 2; format.nSamplesPerSec = Rate;
        format.wBitsPerSample = 32; format.nBlockAlign = 8; format.nAvgBytesPerSec = Rate * 8;
        hr = client->Initialize(AUDCLNT_SHAREMODE_SHARED,
            AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK
                | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
            200000, 0, &format, nullptr);
        if (SUCCEEDED(hr)) hr = client->SetEventHandle(samples);
        return hr;
    }

    void receive(IAudioCaptureClient* capture) {
        UINT32 pending = 0;
        for (unsigned packet = 0; packet < 128; ++packet) {
            HRESULT hr = capture->GetNextPacketSize(&pending);
            if (FAILED(hr)) { error = unsigned(hr); state.fetch_and(~2u); return; }
            if (!pending) return;
            BYTE* data = nullptr; UINT32 frames = 0; DWORD flags = 0;
            hr = capture->GetBuffer(&data, &frames, &flags, nullptr, nullptr);
            if (FAILED(hr)) { error = unsigned(hr); state.fetch_and(~2u); return; }
            {
                std::lock_guard<std::mutex> lock(mutex);
                const unsigned take = std::min(frames, Frames);
                const unsigned keep = std::min(count, Frames - take);
                if (keep) std::memmove(pcm.data(), pcm.data() + (count - keep) * 2, keep * 2 * sizeof(float));
                if ((flags & AUDCLNT_BUFFERFLAGS_SILENT) || !data)
                    std::fill_n(pcm.data() + keep * 2, take * 2, 0.f);
                else std::memcpy(pcm.data() + keep * 2,
                    reinterpret_cast<const float*>(data) + (frames - take) * 2, take * 2 * sizeof(float));
                count = keep + take; ++sequence; stamp = GetTickCount64();
            }
            capture->ReleaseBuffer(frames);
        }
    }

    void run() {
        struct Apartment {
            HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
            ~Apartment() { if (SUCCEEDED(hr)) CoUninitialize(); }
        } apartment;
        if (FAILED(apartment.hr)) { error = unsigned(apartment.hr); return; }
        ComPtr<IMMDeviceEnumerator> enumerator;
        if (control && FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
                                    IID_PPV_ARGS(&enumerator)))) return;
        state = control ? 1 : 0;
        std::map<std::wstring, Session> held;
        ComPtr<IAudioClient> client; ComPtr<IAudioCaptureClient> capture;
        HRESULT hr = activate(client);
        if (SUCCEEDED(hr)) hr = client->GetService(IID_PPV_ARGS(&capture));
        if (SUCCEEDED(hr)) hr = client->Start();
        if (SUCCEEDED(hr)) state.fetch_or(2); else { error = unsigned(hr); capture.Reset(); }
        std::uint64_t last_scan = 0;
        HANDLE events[]{stop, samples, changed};
        while (WaitForSingleObject(stop, 0) != WAIT_OBJECT_0) {
            DWORD event = WaitForMultipleObjects(3, events, FALSE, 200);
            if (event == WAIT_OBJECT_0) break;
            if (capture && (state.load() & 2)) receive(capture.Get());
            const auto now = GetTickCount64();
            if (control && (event == WAIT_OBJECT_0 + 2 || now - last_scan >= 250)) {
                update_sessions(enumerator.Get(), held); last_scan = now;
            }
        }
        if (client && capture) client->Stop();
        // Leave Windows' prior per-app mixer setting in place on clean exit.
        for (auto& entry : held) {
            float current = -1;
            if (SUCCEEDED(entry.second.volume->GetMasterVolume(&current))
                && std::abs(current - entry.second.applied) < .0001f)
                entry.second.volume->SetMasterVolume(entry.second.original, nullptr);
        }
        state = 0;
    }
};

static void* start_bus(unsigned pid, float gain, bool control) {
    if (!pid || !std::isfinite(gain) || gain < 0 || gain > 1) return nullptr;
    try {
        auto owner = std::make_unique<Bus>(pid, gain, control);
        auto* bus = owner.get();
        if (!bus->stop || !bus->samples || !bus->changed) return nullptr;
        bus->worker = std::thread([bus] { bus->run(); });
        return owner.release();
    } catch (...) { return nullptr; }
}
extern "C" {
__declspec(dllexport) unsigned gga_abi_version() { return 1; }
__declspec(dllexport) void* gga_start(unsigned pid, float gain) { return start_bus(pid, gain, true); }
__declspec(dllexport) void* gga_capture_start(unsigned pid) { return start_bus(pid, 1, false); }
__declspec(dllexport) void gga_stop(void* handle) { delete static_cast<Bus*>(handle); }
__declspec(dllexport) void gga_gain(void* handle, float level) {
    if (!handle || !std::isfinite(level)) return;
    auto* bus = static_cast<Bus*>(handle);
    bus->gain = std::clamp(level, 0.f, 1.f); SetEvent(bus->changed);
}
__declspec(dllexport) unsigned gga_state(void* handle) { return handle ? static_cast<Bus*>(handle)->state.load() : 0; }
__declspec(dllexport) unsigned gga_error(void* handle) { return handle ? static_cast<Bus*>(handle)->error.load() : 0; }
__declspec(dllexport) unsigned gga_sessions(void* handle) { return handle ? static_cast<Bus*>(handle)->sessions.load() : 0; }
__declspec(dllexport) float gga_observed_gain(void* handle) { return handle ? static_cast<Bus*>(handle)->observed_gain.load() : -1; }
__declspec(dllexport) unsigned gga_renderers(void* handle, unsigned* output, unsigned capacity) {
    if (!handle || !output || !capacity) return 0;
    auto* bus = static_cast<Bus*>(handle);
    std::lock_guard<std::mutex> lock(bus->renderer_mutex);
    const unsigned count = std::min(capacity, unsigned(bus->renderers.size()));
    std::copy_n(bus->renderers.data(), count, output);
    return count;
}
__declspec(dllexport) unsigned gga_read(void* handle, float* output, unsigned capacity, std::uint64_t* sequence) {
    if (!handle || !output || capacity < Frames || !sequence) return 0;
    auto* bus = static_cast<Bus*>(handle);
    std::lock_guard<std::mutex> lock(bus->mutex);
    if (!bus->count || GetTickCount64() - bus->stamp > 250 || *sequence == bus->sequence) return 0;
    std::fill_n(output, (Frames - bus->count) * 2, 0.f);
    std::copy_n(bus->pcm.data(), bus->count * 2, output + (Frames - bus->count) * 2);
    *sequence = bus->sequence;
    return Frames;
}
}
