---
name: gg-live-eyes
description: Visually observe GG AI DESKTOP, Blender EXT or a video URL while working, using a bounded 25 fps RAM capture and timestamped frame sequences. Use for visual feedback or motion/video inspection, not as a substitute for measurement or a claim of complete understanding from sparse samples.
---

# GG live eyes

The screen is captured at **up to 25 fps**. Windows uses short on-demand
observations; Linux can keep a bounded capture service. Model interpretation is tool-driven;
capture speed is not reasoning speed. Motion previews occupy a ring of up to
six seconds, limited to 32 MiB of image data; detailed screens can shorten that
window. A single latest RGB detail frame uses at most another 32 MiB; native
detail images are encoded only on request. Status reports both allocations.
Pipeline working buffers and encoding need additional temporary RAM.
No video archive or persistent bitmap cache is
created. The capture expires after 15 minutes without observation requests or
four hours per session. KDE can reconnect on the next authorized observation;
use start if an older client needs it. Capture does not itself grant a new task.
MCP image delivery also starts the existing Codex bitmap-history guard for its
own home. That removes selected image payloads from durable rollouts after
delivery; do not describe this as a guarantee that Codex never writes them.

## Screen observation

Use the `gg-eyes` MCP tools when connected. The same tools are callable here:

```text
python3 -B gg-eyes start
python3 -B gg-eyes status
python3 -B gg-eyes frame
python3 -B gg-eyes clip --seconds 2 --fps 25
python3 -B gg-eyes stop
```

### Windows

Run `gg-eyes.cmd` from the workspace (the `python3` Windows Store alias may
not be a Python installation). `frame` and `clip --seconds 2 --fps 25` use a
hidden, short-lived Win32/Pillow capture worker. It has a 256 MiB process memory
limit and an eight-second request deadline; a timeout stops only that helper
and its descendants. The app's Qt UI is never asked to render a screenshot.
The preview is at most 960×540, the JPEG ring at most 32 MiB / six seconds,
and no image files or background capture service are created.
Use this Windows path for observations. `gg-desk snapshot --visual` still
uses synchronous Qt capture and is not the Windows eyes provider.

Windows CLI images return an MCP-style `content` JSON envelope directly over
stdout. Parse that result inside a tool adapter and display each image block
with `image(...)`; print only the text metadata, never the base64 payload.
Do not pass this output to a disk image file. MCP also delivers images directly.
`start` reports `ready`, not `live`; `status` reports `off` between observations
because no daemon is running. A delivered observation reports its actual fps,
coverage, gaps and capture timestamps. On Windows `--age` is unsupported since
no frames survive the request. Inspect chronological clip sheets, or request a
fresh detail frame instead.

Both `frame` and `clip` accept `--region X Y WIDTH HEIGHT` on Windows. These
are primary-screen physical pixels, selected from an inspected full frame.
Use a region to make moving details readable in the clip sheets. `frame --crop`
still crops the returned image. The optional region is Windows-specific; omit
it for Linux captures. Stop/end the observation workflow when the task ends.

### Linux

On this authorized KDE workstation, GG's dedicated native capture executable
connects directly to the same bound screen. Reuse it during the approved task;
do not ask the user to reapprove ordinary observations. Status reports
`provider: kde-native` and `requires_selection: false`. The capture service
survives an app restart and retains its bounded RAM buffers and expiry limits.
Other environments can use the visible portal selector. Report actual provider
state; an installed helper or a start request alone does not prove a live image.
The Linux CLI returns image paths on **tmpfs**; open them with the image tool. MCP
returns images directly. Do not print base64 into chat or copy RAM images into
the repository, ordinary temporary directories or research archives.

Fetch a frame before work and after meaningful mouse/key or modeling steps.
Actually inspect it before continuing. For motion fetch a clip: every selected
frame appears in chronological contact sheets, labelled with frame times and
IDs. Native KDE uses capture-completion timestamps and has no compositor PTS;
PipeWire/video can supply presentation timestamps. Check actual fps, coverage,
frame age and gaps. Expand critical
frames with `frame --age SECONDS` or crop the latest image with
`frame --crop X Y WIDTH HEIGHT` while the frame remains in the ring.
Stale images fail rather than silently masquerading as current views.

The default latest frame uses native resolution, capped at 4096×2160. Motion
frames, including `frame --age SECONDS`, are smaller previews. Crop coordinates
refer to the requested frame's pixels, not to the preview's pixels by default.
For pixel details crop the latest native frame rather than enlarging a preview.
Use the returned `image_to_monitor` mapping when available; convert source size
and monitor position and subtract the app window origin before driving the
approved visible `gg-desk` mouse/keyboard. An image does not prove
mesh integrity, correct weights, UVs, or animation data; inspect those directly
as needed. End capture when the visual task ends.

## Video inspection

```text
python3 -B gg-eyes video URL_OR_FILE --start 120 --seconds 2 --fps 25
python3 -B gg-eyes video URL_OR_FILE --start 120.5 --seconds 0.08 --detail
```

The video tool resolves public media links and decodes only the requested
interval through FFmpeg pipes. It returns decoder timestamps, not fabricated
playback times, and retains no full video file. It supplies visual evidence;
**it does not transcribe audio**. Separate observed visuals, spoken explanations,
on-screen text and assumptions. Captions containing music/lyrics are not
technical narration. Never claim the entire video was watched from one clip.

For a long tutorial, establish sections from its available metadata, inspect
representative visual passages, then examine relevant demonstrations densely
and track what intervals were actually observed. For animation examine the
whole short action at 25 fps; expand details where sheets are too small. Say
which portions and audio were not examined. A native video API can supplement
this only when that provider is connected and its use is authorized; do not
silently obtain keys, install model weights or create large downloads.
