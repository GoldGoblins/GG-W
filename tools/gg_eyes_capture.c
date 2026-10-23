/* Dedicated executable identity for KDE's per-application screen permission.
 * Embeds only the fixed capture service; this is not a general Python launcher.
 */
#include <dlfcn.h>
#include <stdio.h>

int main(void)
{
    void *library = dlopen("libpython3.so", RTLD_NOW | RTLD_GLOBAL);
    if (!library) {
        fputs("GG screen capture: Python runtime unavailable\n", stderr);
        return 1;
    }
    int (*python_main)(int, char **) = dlsym(library, "Py_BytesMain");
    if (!python_main) {
        fputs("GG screen capture: Python entry unavailable\n", stderr);
        return 1;
    }
    char *arguments[] = {
        "/usr/bin/python3", "-c",
        "import sys; sys.dont_write_bytecode = True; "
        "sys.path.insert(0, '/home/GG/GoldGoblins/projects/gg-ai-desktop'); "
        "from backend.live_vision_capture import serve; serve(native=True)",
        NULL
    };
    return python_main(3, arguments);
}
