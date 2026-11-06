"""WASAPI speaker-loopback capture, stored as a temporary PCM WAV for muxing."""
import threading
import time
import wave


def devices():
    import pyaudiowpatch as pa
    with pa.PyAudio() as manager:
        rows = list(manager.get_loopback_device_info_generator())
        try:
            default = manager.get_default_wasapi_loopback()['index']
        except OSError:
            default = None
    return rows, default


class AudioCapture:
    def __init__(self, path, device):
        import pyaudiowpatch as pa
        self.pa = pa
        self.manager = pa.PyAudio()
        self.rate = int(device['defaultSampleRate'])
        self.channels = min(2, int(device['maxInputChannels']))
        if self.channels < 1:
            self.manager.terminate()
            raise ValueError('Selected loopback device has no input channels')
        self.frames = 0
        self.errors = []
        self.lock = threading.Lock()
        self.started = None
        self.file = wave.open(str(path), 'wb')
        self.file.setnchannels(self.channels)
        self.file.setsampwidth(2)
        self.file.setframerate(self.rate)
        try:
            self.stream = self.manager.open(format=pa.paInt16, channels=self.channels,
                rate=self.rate, input=True, input_device_index=device['index'],
                frames_per_buffer=1024, stream_callback=self.callback, start=False)
        except Exception:
            self.file.close()
            self.manager.terminate()
            raise

    def silence(self, frames):
        while frames > 0:
            n = min(frames, self.rate)
            self.file.writeframesraw(bytes(n * self.channels * 2))
            self.frames += n
            frames -= n

    def callback(self, data, frame_count, timing, status):
        try:
            with self.lock:
                # Some loopback endpoints stop delivering packets during silence.
                # Restore long wall-clock gaps instead of collapsing the audio timeline.
                elapsed = max(0, time.monotonic() - self.started)
                expected = max(0, int(elapsed * self.rate) - frame_count)
                if expected - self.frames > self.rate // 4:
                    self.silence(expected - self.frames)
                payload = data or bytes(frame_count * self.channels * 2)
                self.file.writeframesraw(payload)
                self.frames += len(payload) // (self.channels * 2)
                if status and len(self.errors) < 20:
                    self.errors.append('PortAudio status ' + str(status))
            return None, self.pa.paContinue
        except Exception as error:
            self.errors.append(str(error))
            return None, self.pa.paAbort

    def start(self):
        self.started = time.monotonic()
        self.stream.start_stream()

    def stop(self):
        try:
            if self.stream.is_active():
                self.stream.stop_stream()
            self.stream.close()
            with self.lock:
                if self.started is not None:
                    target = int((time.monotonic() - self.started) * self.rate)
                    self.silence(max(0, target - self.frames))
                self.file.close()
        finally:
            self.manager.terminate()
