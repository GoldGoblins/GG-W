# Windows WEB filtering host

`gg_webview.cpp` is GG's Windows x64 WebView2 host. It uses Microsoft's native
COM API to enable browser extensions and load the original uBlock Origin
Chromium package. Qt's existing WebView2 host remains available when the
optional filtering installation is absent.

Build/install through `tools/install_web_filter.py`. The tool obtains the SDK
and extension from their original publishers; SDK headers and extension source
are not bundled into this repository. The original extension is unmodified,
installed outside the source tree, and retains its GPLv3 license and sources.
Microsoft's SDK license and notice accompany the compiled GG host here.

All COM operations happen on the owning Qt GUI thread. Browser operations and
extension startup are asynchronous. Native events use a bounded queue, and
JavaScript results have size and deadline limits. Diagnostics use the native
DevTools API of that owned WebView; no debugging port or page host object is
exposed. GG's first navigation waits until uBO's own startup has completed.
The Qt wrapper returns native keyboard focus to its owning window when a user
clicks a desktop control outside WebView2. Browser clicks retain normal player
shortcuts; the regression uses Windows input rather than Qt-only key delivery.

Run the native regressions with the installed extension:

```powershell
.venv-windows\Scripts\python.exe -B -m unittest discover -s tests -p test_web_content_blocker.py -v
.venv-windows\Scripts\python.exe -B -m unittest discover -s tests -p test_windows_webview.py -v
```
