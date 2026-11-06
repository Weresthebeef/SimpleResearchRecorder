"""Windows screen/window recorder with optional system-output audio."""
import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import os
import shutil
import subprocess
import time
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent


def window_targets():
    user = ctypes.windll.user32
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsIconic.argtypes = [wintypes.HWND]
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    result = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    @callback_type
    def callback(handle, data):
        if not user.IsWindowVisible(handle) or user.IsIconic(handle):
            return True
        n = user.GetWindowTextLengthW(handle)
        if not n:
            return True
        title = ctypes.create_unicode_buffer(n + 1)
        user.GetWindowTextW(handle, title, n + 1)
        if title.value == 'Simple Research Recorder':
            return True
        rect = wintypes.RECT()
        if user.GetClientRect(handle, ctypes.byref(rect)) and rect.right > 0 and rect.bottom > 0:
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
            result.append(dict(kind='window', hwnd=int(handle), pid=pid.value, title=title.value,
                               bounds=(0, 0, rect.right, rect.bottom)))
        return True
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows(callback, 0)
    return sorted(result, key=lambda row: row['title'].lower())


def monitors():
    result = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE,
                                      wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    @callback_type
    def callback(handle, dc, rect, data):
        r = rect.contents
        result.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, callback, 0)
    return result


def output_dimensions(bounds, half_size=True):
    _, _, width, height = bounds
    if half_size:
        # H.264 yuv420p needs even dimensions; round half-size down to even.
        return max(2, width // 4 * 2), max(2, height // 4 * 2)
    return (width + 1) // 2 * 2, (height + 1) // 2 * 2


def capture_command(ffmpeg, bounds, fps, output, half_size=True, hwnd=None):
    x, y, width, height = bounds
    out_width, out_height = output_dimensions(bounds, half_size)
    filters = (f'scale={out_width}:{out_height}:flags=bicubic' if half_size
               else 'pad=ceil(iw/2)*2:ceil(ih/2)*2')
    command = [str(ffmpeg), '-hide_banner', '-loglevel', 'warning', '-n',
            '-f', 'gdigrab', '-framerate', str(fps), '-draw_mouse', '0',
            ]
    if hwnd is None:
        command += ['-offset_x', str(x), '-offset_y', str(y), '-video_size', f'{width}x{height}', '-i', 'desktop']
    else:
        command += ['-i', f'hwnd={hwnd}']
    return command + ['-an', '-vf', filters,
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output)]


class Recorder:
    def __init__(self, window):
        self.window = window
        self.process = None
        self.log = None
        self.output = None
        self.stopping = False
        self.closing = False
        self.countdown = False
        self.started = 0
        self.audio_capture = None
        self.finalize_result = None
        self.finishing = False
        self.key = 'F8'
        self.hotkey = False
        for label, modifiers, key in [('F8', 0x4000, 0x77), ('F9', 0x4000, 0x78), ('Ctrl+Shift+R', 0x4006, 0x52)]:
            if ctypes.windll.user32.RegisterHotKey(None, 1, modifiers, key):
                self.key, self.hotkey = label, True
                break
        self.folder = tk.StringVar(value=str(Path.home() / 'Videos' / 'DI Research'))
        self.ffmpeg = tk.StringVar(value=shutil.which('ffmpeg') or r'C:\ffmpeg\bin\ffmpeg.exe')
        self.fps = tk.StringVar(value='30')
        self.half_size = tk.BooleanVar(value=True)
        self.dimensions = tk.StringVar()
        self.status = tk.StringVar(value='Ready. Choose a screen/window and optional system audio.')
        self.targets = []
        self.audio_devices = []
        window.title('Simple Research Recorder')
        window.resizable(False, False)
        frame = ttk.Frame(window, padding=16)
        frame.grid()
        ttk.Label(frame, text='Capture target').grid(row=0, column=0, sticky='w')
        self.screen = ttk.Combobox(frame, state='readonly', width=43)
        self.screen.grid(row=0, column=1, sticky='ew')
        self.screen.bind('<<ComboboxSelected>>', lambda event: self.update_dimensions())
        ttk.Button(frame, text='Refresh', command=self.refresh_targets).grid(row=0, column=2)
        ttk.Label(frame, text='Frame rate').grid(row=1, column=0, sticky='w', pady=8)
        ttk.Combobox(frame, textvariable=self.fps, values=['30', '60'], state='readonly', width=6).grid(row=1, column=1, sticky='w')
        ttk.Checkbutton(frame, text='Half resolution (50% width and height)',
                        variable=self.half_size, command=self.update_dimensions).grid(row=2, column=0, columnspan=3, sticky='w')
        ttk.Label(frame, textvariable=self.dimensions).grid(row=3, column=0, columnspan=3, sticky='w', pady=(0, 8))
        ttk.Label(frame, text='Sound').grid(row=4, column=0, sticky='w')
        self.audio = ttk.Combobox(frame, state='readonly', width=43)
        self.audio.grid(row=4, column=1, columnspan=2, sticky='ew')
        ttk.Label(frame, text='System audio includes all apps on the chosen output. No microphone.').grid(row=5, column=0, columnspan=3, sticky='w')
        self.refresh_targets()
        for row, label, variable, action in [
            (6, 'Save folder', self.folder, self.choose_folder),
            (7, 'FFmpeg', self.ffmpeg, self.choose_ffmpeg),
        ]:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w')
            ttk.Entry(frame, textvariable=variable, width=46).grid(row=row, column=1, pady=5)
            ttk.Button(frame, text='Browse', command=action).grid(row=row, column=2, padx=6)
        self.button = ttk.Button(frame, text=f'Start recording ({self.key})', command=self.toggle)
        self.button.grid(row=8, column=0, columnspan=2, sticky='ew', pady=12)
        ttk.Button(frame, text='Open folder', command=self.open_folder).grid(row=8, column=2)
        ttk.Label(frame, textvariable=self.status, wraplength=540).grid(row=9, column=0, columnspan=3, sticky='w')
        ttk.Label(frame, text=f'Starts after 3 seconds and minimizes. Use {self.key} to stop.\nKeep target window open and not minimized. Use borderless/windowed for games.').grid(row=10, column=0, columnspan=3, sticky='w', pady=(12, 0))
        if not self.hotkey:
            self.status.set('Global shortcuts unavailable. Use Start/Stop; Alt+Tab back here to stop.')
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.after(100, self.tick)

    def update_dimensions(self):
        if not self.targets or self.screen.current() < 0:
            return
        width, height = output_dimensions(self.targets[self.screen.current()]['bounds'], self.half_size.get())
        self.dimensions.set(f'Output: {width} × {height} — compressed H.264 MP4')

    def refresh_targets(self):
        if self.process or self.countdown or self.finishing:
            return
        previous = self.screen.get()
        previous_sound = self.audio.get()
        self.targets = [dict(kind='screen', bounds=b, title=f'Screen {i+1}: {b[2]} × {b[3]}') for i,b in enumerate(monitors())] + window_targets()
        names = [r['title'] if r['kind']=='screen' else f"Window: {r['title']} [{r['hwnd']:X}]" for r in self.targets]
        self.screen.configure(values=names)
        if names:
            self.screen.current(names.index(previous) if previous in names else 0)
        try:
            from audio_capture import devices
            self.audio_devices, default = devices()
            sounds = ['No sound'] + [d['name'] for d in self.audio_devices]
            self.audio.configure(values=sounds)
            self.audio.current(sounds.index(previous_sound) if previous_sound in sounds else next((i+1 for i,d in enumerate(self.audio_devices) if d['index']==default),0))
        except Exception as error:
            self.audio_devices = []
            self.audio.configure(values=['No sound'])
            self.audio.current(0)
            self.status.set('System audio unavailable: ' + str(error))
        self.update_dimensions()

    def selected_target(self):
        index = self.screen.current()
        if index < 0:
            raise ValueError('Choose a capture target first.')
        target = self.targets[index].copy()
        if target['kind']=='window':
            user=ctypes.windll.user32
            pid=wintypes.DWORD()
            user.GetWindowThreadProcessId(target['hwnd'],ctypes.byref(pid))
            if pid.value!=target['pid'] or user.IsIconic(target['hwnd']):
                raise ValueError('Window closed/changed or is minimized. Restore it and click Refresh.')
            rect=wintypes.RECT()
            if not user.GetClientRect(target['hwnd'],ctypes.byref(rect)) or rect.right<=0 or rect.bottom<=0:
                raise ValueError('Window has no visible client area.')
            target['bounds']=(0,0,rect.right,rect.bottom)
        return target

    def choose_folder(self):
        if not self.process and not self.countdown:
            value = filedialog.askdirectory(initialdir=self.folder.get())
            if value:
                self.folder.set(value)

    def choose_ffmpeg(self):
        value = filedialog.askopenfilename(filetypes=[('FFmpeg executable', '*.exe')])
        if value:
            self.ffmpeg.set(value)

    def open_folder(self):
        folder = Path(self.folder.get())
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def toggle(self):
        if self.stopping:
            return
        if self.process:
            self.stop()
        elif self.countdown:
            self.countdown = False
            self.button.configure(text=f'Start recording ({self.key})')
            self.status.set('Countdown cancelled.')
        else:
            if not Path(self.ffmpeg.get()).is_file():
                messagebox.showerror('FFmpeg missing', 'Browse to ffmpeg.exe first.')
                return
            self.countdown = True
            self.button.configure(text=f'Cancel countdown ({self.key})')
            self.start_countdown(3)

    def start_countdown(self, seconds):
        if not self.countdown:
            return
        if seconds:
            self.status.set(f'Recording starts in {seconds}…')
            self.window.after(1000, lambda: self.start_countdown(seconds - 1))
            return
        self.countdown = False
        try:
            folder = Path(self.folder.get())
            folder.mkdir(parents=True, exist_ok=True)
            self.output = folder / (datetime.now().strftime('Research_%Y%m%d_%H%M%S_%f') + '.mp4')
            self.log = self.output.with_suffix('.log').open('wb')
            target = self.selected_target()
            self.active_ffmpeg = self.ffmpeg.get()
            self.video_output = self.output.with_suffix('.video.mp4')
            self.audio_output = self.output.with_suffix('.audio.wav')
            audio_index = self.audio.current()-1
            if audio_index>=0:
                from audio_capture import AudioCapture
                self.audio_capture = AudioCapture(self.audio_output,self.audio_devices[audio_index])
            command = capture_command(self.active_ffmpeg, target['bounds'], int(self.fps.get()),
                                      self.video_output, self.half_size.get(), target.get('hwnd'))
            self.log.write((f'Encoding: H.264, veryfast, CRF 24; target={target}; sound={self.audio.get()}\n').encode('utf-8'))
            self.log.flush()
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                            stdout=subprocess.DEVNULL, stderr=self.log,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
            if self.audio_capture:
                self.audio_capture.start()
            self.started = time.monotonic()
            self.button.configure(text=f'Stop recording ({self.key})')
            self.window.iconify()
        except Exception as error:
            if self.process:
                self.process.kill()
                self.process.wait(timeout=5)
                self.process.stdin.close()
            if self.audio_capture:
                self.audio_capture.stop()
                self.audio_capture = None
            if self.log:
                self.log.close()
            self.log = None
            self.process = None
            self.button.configure(text=f'Start recording ({self.key})')
            messagebox.showerror('Could not start', str(error))

    def stop(self):
        self.stopping = True
        self.status.set('Finishing MP4… please wait.')
        self.button.configure(state='disabled')
        try:
            self.process.stdin.write(b'q\n')
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def tick(self):
        msg = wintypes.MSG()
        # Consume only our WM_HOTKEY messages, leaving Tk's window messages alone.
        if self.hotkey:
            while ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), None, 0x312, 0x312, 1):
                if msg.wParam == 1:
                    self.toggle()
        if self.process:
            code = self.process.poll()
            if code is None:
                if not self.stopping:
                    elapsed = int(time.monotonic() - self.started)
                    self.status.set(f'Recording {elapsed//60:02}:{elapsed%60:02} — {self.key} to stop')
            else:
                self.process.stdin.close()
                self.process = None
                self.log.close()
                self.log = None
                self.stopping = True
                self.finishing = True
                self.status.set('Finishing audio and MP4…')
                self.button.configure(state='disabled')
                threading.Thread(target=self.finalize,args=(code,),daemon=False).start()
        if self.finishing and self.finalize_result is not None:
            self.finishing = False
            self.stopping = False
            error = self.finalize_result.get('error')
            self.finalize_result = None
            self.button.configure(state='normal',text=f'Start recording ({self.key})')
            self.window.deiconify()
            self.status.set(f'Saved: {self.output}' if not error else 'Could not finish: ' + error)
            if self.closing:
                self.destroy()
                return
        self.window.after(100, self.tick)

    def finalize(self, video_code):
        try:
            audio = self.audio_capture
            self.audio_capture = None
            if audio:
                audio.stop()
            if video_code!=0 or not self.video_output.exists() or not self.video_output.stat().st_size:
                raise RuntimeError('Video capture failed; see ' + str(self.output.with_suffix('.log')))
            if audio:
                if audio.errors:
                    raise RuntimeError('Audio capture reported errors. Temporary video/WAV retained; see log.')
                command=[self.active_ffmpeg,'-hide_banner','-loglevel','warning','-n','-i',str(self.video_output),
                         '-i',str(self.audio_output),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','128k',
                         '-af','aresample=async=1:first_pts=0,apad','-shortest','-movflags','+faststart',str(self.output)]
                with self.output.with_suffix('.log').open('ab') as log:
                    log.write(('Audio diagnostics: '+repr(audio.errors)+'\n').encode())
                    result=subprocess.run(command,stdout=subprocess.DEVNULL,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode:
                    raise RuntimeError('Audio/video mux failed. Temporary files retained; see log.')
                self.video_output.unlink()
                self.audio_output.unlink()
            else:
                self.video_output.rename(self.output)
            self.finalize_result={}
        except Exception as error:
            if 'audio' in locals() and audio and audio.errors:
                with self.output.with_suffix('.log').open('ab') as log:
                    log.write(('Audio errors: '+repr(audio.errors)+'\n').encode())
            self.finalize_result={'error':str(error)}

    def close(self):
        self.countdown = False
        if self.finishing:
            self.closing = True
        elif self.process:
            self.closing = True
            if not self.stopping:
                self.stop()
        else:
            self.destroy()

    def destroy(self):
        if self.hotkey:
            ctypes.windll.user32.UnregisterHotKey(None, 1)
        self.window.destroy()


if __name__ == '__main__':
    ctypes.windll.user32.SetProcessDPIAware()
    app = tk.Tk()
    Recorder(app)
    app.mainloop()
