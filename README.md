# Simple Research Recorder

A lightweight **Windows screen and window recorder** for capturing gameplay tests, software demonstrations, and research footage.

The recorder combines a Python/Tkinter interface, FFmpeg video capture, and optional WASAPI system audio. It runs separately from the recorded application and does not inject code or modify game files.

## Features

- Record an entire display or a selected application window.
- Optional system-output audio, with an output-device selector.
- Half resolution enabled by default: **50% width and 50% height**. A 2560×1440 capture becomes 1280×720.
- Full-resolution option and 30/60 FPS selection.
- H.264 MP4 video using the `veryfast` preset and CRF 24.
- AAC audio at 128 kb/s when sound is enabled.
- Three-second start countdown and automatic recorder minimization.
- Global start/stop shortcut, with alternatives if the preferred key is occupied.
- Unique recording filenames and an adjacent diagnostic log.
- Background audio/video finalization after capture stops.

## Requirements

- Windows.
- **Python 3.11 with Tkinter** is the tested configuration.
- FFmpeg with `gdigrab` window/display capture and `libx264` encoding.
- **PyAudioWPatch 0.2.12.9** for optional WASAPI loopback audio.

FFmpeg and Python are not bundled. PyAudioWPatch is listed in `requirements.txt`.

## Setup

Install Python and FFmpeg, then open a terminal in the project directory:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Double-click **Start Recorder.cmd**, or run:

```powershell
.venv\Scripts\python.exe screen_recorder.py
```

The source-package launcher prefers the local `.venv` and otherwise uses the Windows Python launcher. The application looks for FFmpeg on `PATH`, then tries `C:\ffmpeg\bin\ffmpeg.exe`. Use **Browse** to select its actual location.

If the audio dependency is unavailable, video-only recording remains available through **No sound**.

## Record a video

1. Select a display or a **Window:** entry under Capture target. Click **Refresh** if you opened the target after starting the recorder.
2. Choose the Sound output device used by the application, or **No sound**.
3. Select the output folder, frame rate, and resolution option.
4. Press **Start** or the shortcut displayed on the button.
5. Return to the application during the three-second countdown.
6. Press the shortcut again to stop. Wait for finalization before using the finished MP4.

The recorder tries **F8**, then **F9**, then **Ctrl+Shift+R**. The displayed shortcut is the one actually registered. If all are occupied, use the Start/Stop button directly.

The default destination is:

```text
%USERPROFILE%\Videos\DI Research
```

Use **Open folder** to find your captures. Closing the recorder during capture finishes the recording before exiting.

## Sound behavior

Audio uses **WASAPI loopback** from the selected Windows output device. It records all applications playing through that device, even when the video targets one window. It does not capture a microphone or isolate one application's audio.

If a recording is silent, check which output device the game is using and select the matching Sound entry. Bluetooth/headset routing changes may require refreshing the device list.

## Window capture limitations

The window mode captures the selected native window's client area. Keep the target open and unminimized, and avoid resizing during recording. A closed/replaced window is rejected at capture startup.

Some accelerated games or exclusive-fullscreen applications can produce black or stale frames through GDI capture. Try windowed/borderless mode or record the display instead. This is not Windows Graphics Capture or an OBS-style game hook, and compatibility is not guaranteed for every renderer.

## Files and finalization

During capture, temporary video and optional PCM WAV files are written separately. After stopping, FFmpeg combines them into the final MP4. Temporary files are removed after successful finalization and retained on failure for recovery. Allow free disk space for temporary audio, and avoid forcibly closing the process while finalizing.

Audio/video synchronization is approximate. Check longer recordings before relying on exact audiovisual timing. Half-size output dimensions are rounded to even values for H.264 compatibility.

## Project files

| File | Purpose |
|---|---|
| `screen_recorder.py` | Interface, capture targets, hotkeys, FFmpeg recording, and finalization |
| `audio_capture.py` | WASAPI loopback capture to temporary PCM WAV |
| `Start Recorder.cmd` | Local virtual-environment/Python launcher |
| `requirements.txt` | Pinned audio dependency |

No recordings, virtual environments, or FFmpeg binaries are included in the source package.

## Verification

The underlying recorder passed Python syntax and UI initialization checks. A real selected-window test recorded a 320×240 window at 160×120, captured the default WASAPI endpoint, and produced an MP4 with H.264 video and an AAC audio track. Window/device enumeration and sound-choice preservation on refresh were also checked.

These checks do not establish compatibility with every game, audibility of a specific application's output, or precision synchronization for long recordings. The public-package launcher removes the original workstation-specific Python fallback; capture source files are unchanged.

## Contributing and credits

Useful improvements include additional capture backends, stronger audio synchronization, saved settings, and clearer error recovery. When reporting an issue, include Windows/Python/FFmpeg versions, capture mode, output device, and the recording's diagnostic log. Review logs for personal paths before posting them.

Uses [FFmpeg](https://ffmpeg.org/), [Python/Tkinter](https://docs.python.org/3/library/tkinter.html), and [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch). Those projects retain their own licenses. No repository-wide license is assigned by this README.
