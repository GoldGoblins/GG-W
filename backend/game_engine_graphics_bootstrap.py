"""Choose the standalone hardware path before constructing a Qt application."""


def configure(environment, *, nvidia_available):
    environment.setdefault('QT_QPA_PLATFORM', 'xcb')
    environment.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
    if not nvidia_available:
        return
    environment.setdefault('__NV_PRIME_RENDER_OFFLOAD', '1')
    environment.setdefault('__GLX_VENDOR_LIBRARY_NAME', 'nvidia')
    environment.setdefault('__VK_LAYER_NV_optimus', 'NVIDIA_only')
    # On a Wayland desktop, PRIME's GLX swap can wait indefinitely on the
    # compositor's cross-device timeline. Use Qt's hardware Vulkan swapchain
    # for this standalone game. An explicitly selected API remains authoritative.
    if (environment.get('QT_QPA_PLATFORM', '').split(':', 1)[0] == 'xcb'
            and environment.get('WAYLAND_DISPLAY')
            and environment.get('__NV_PRIME_RENDER_OFFLOAD') == '1'):
        environment.setdefault('QSG_RHI_BACKEND', 'vulkan')
