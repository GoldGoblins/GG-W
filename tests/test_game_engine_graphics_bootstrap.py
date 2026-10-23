import unittest
from backend.game_engine_graphics_bootstrap import configure


class GraphicsBootstrap(unittest.TestCase):
    def test_prime_xwayland_uses_hardware_vulkan(self):
        environment = dict(WAYLAND_DISPLAY='wayland-0', QT_QPA_PLATFORM='xcb')
        configure(environment, nvidia_available=True)
        self.assertEqual(environment['QSG_RHI_BACKEND'], 'vulkan')
        self.assertEqual(environment['__VK_LAYER_NV_optimus'], 'NVIDIA_only')

    def test_explicit_renderer_selection_is_preserved(self):
        for api in ('opengl', 'vulkan', 'software'):
            environment = dict(WAYLAND_DISPLAY='wayland-0', QSG_RHI_BACKEND=api)
            configure(environment, nvidia_available=True)
            self.assertEqual(environment['QSG_RHI_BACKEND'], api)

    def test_ordinary_xorg_does_not_change_the_renderer_default(self):
        environment = dict(DISPLAY=':0')
        configure(environment, nvidia_available=True)
        self.assertNotIn('QSG_RHI_BACKEND', environment)

    def test_native_wayland_and_headless_platforms_keep_their_selected_path(self):
        for platform in ('wayland', 'offscreen', 'minimal'):
            environment = dict(WAYLAND_DISPLAY='wayland-0', QT_QPA_PLATFORM=platform)
            configure(environment, nvidia_available=True)
            self.assertEqual(environment['QT_QPA_PLATFORM'], platform)
            self.assertNotIn('QSG_RHI_BACKEND', environment)

    def test_missing_or_explicitly_disabled_offload_does_not_choose_nvidia_api(self):
        for nvidia, offload in ((False, '1'), (True, '0')):
            environment = dict(WAYLAND_DISPLAY='wayland-0', __NV_PRIME_RENDER_OFFLOAD=offload)
            configure(environment, nvidia_available=nvidia)
            self.assertNotIn('QSG_RHI_BACKEND', environment)


if __name__ == '__main__':unittest.main()
