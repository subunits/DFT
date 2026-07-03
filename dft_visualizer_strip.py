#!/usr/bin/env python3
import sys
import wave
import numpy as np
import scipy.fftpack as fftpack
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

class NativeAudioSource:
    def __init__(self, filepath: str):
        self.wf = wave.open(filepath, 'rb')
        self.sample_rate = self.wf.getframerate()
        self.channels = self.wf.getnchannels()
        self.sampwidth = self.wf.getsampwidth()
        self.n_frames = self.wf.getnframes()

    def read_all(self) -> np.ndarray:
        raw_bytes = self.wf.readframes(self.n_frames)
        if self.sampwidth == 2:
            data = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        elif self.sampwidth == 1:
            data = (np.frombuffer(raw_bytes, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        elif self.sampwidth == 4:
            data = np.frombuffer(raw_bytes, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            raise ValueError(f"Unsupported wave bit-depth width: {self.sampwidth}")
            
        if self.channels > 1:
            data = data.reshape(-1, self.channels)
            data = np.mean(data, axis=1)
        return data

    def close(self):
        self.wf.close()

def render_wav_animation(filepath: str, window_size: int = 2048, hop_size: int = 512, onset_threshold: float = 0.15):
    try:
        source = NativeAudioSource(filepath)
        fs = source.sample_rate
        full_signal = source.read_all()
        source.close()
    except Exception as e:
        print(f"Error loading WAV file '{filepath}': {e}")
        return

    # Setup the figure and axes
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7))
    
    # Initialize empty line plots for the animation
    line1, = ax1.plot([], [], color='g')
    line2, = ax2.plot([], [], color='c')
    
    # Setup plot limits and static labels
    ax1.set_title("Time Domain Oscilloscope")
    ax1.set_ylim(-1.0, 1.0)
    ax1.set_xlim(0, window_size)
    ax1.grid(True, alpha=0.3)

    ax2.set_title("DFT Spectrum Magnitude Analysis")
    ax2.set_xlim(0, 4000)  
    ax2.set_ylim(0, 50)
    ax2.set_xlabel("Frequency (Hz)")
    ax2.set_ylabel("Magnitude (dB)")
    ax2.grid(True, alpha=0.3)

    # Pre-calculate frequencies for the X-axis of the DFT
    freqs = np.fft.fftfreq(window_size, 1.0 / fs)[:window_size // 2]
    hann_window = np.hanning(window_size)

    # Persistent list for annotations so we can clear them each frame
    annotations = []

    # Frame generator function based on hop_size
    num_frames = (len(full_signal) - window_size) // hop_size
    
    def update(frame):
        # Clear previous frame's peak annotations
        while annotations:
            annotations.pop().remove()
            
        start_idx = frame * hop_size
        end_idx = start_idx + window_size
        chunk = full_signal[start_idx:end_idx]
        
        # Calculate current timestamp in seconds
        current_time_sec = start_idx / fs
        fig.suptitle(f"DFT Audio Analysis: {filepath} | Time: {current_time_sec:.2f}s", fontsize=14)

        # 1. Time Domain Update
        line1.set_data(np.arange(window_size), chunk)

        # 2. Frequency Domain Update
        windowed_signal = chunk * hann_window
        fft_complex = fftpack.fft(windowed_signal)
        fft_mag = np.abs(fft_complex[:window_size // 2]) / (window_size / 2)
        fft_mag_db = 20 * np.log10(fft_mag + 1e-5) + 40 
        
        line2.set_data(freqs, fft_mag_db)

        # 3. Dynamic Peak Detection & Annotation
        peak_count = 0
        for i in range(1, len(fft_mag_db) - 1):
            if peak_count >= 3:
                break
            if fft_mag_db[i] > fft_mag_db[i-1] and fft_mag_db[i] > fft_mag_db[i+1]:
                if fft_mag_db[i] > (onset_threshold * 50.0):
                    freq_hz = freqs[i]
                    mag_val = fft_mag_db[i]
                    if freq_hz < 20.0:
                        continue
                    
                    anno = ax2.annotate(f"{freq_hz:.0f} Hz", 
                                 xy=(freq_hz, mag_val), 
                                 xytext=(freq_hz, mag_val + 3),
                                 arrowprops=dict(arrowstyle="->", color='y'),
                                 color='y', 
                                 horizontalalignment='center')
                    annotations.append(anno)
                    peak_count += 1

        return [line1, line2] + annotations

    # Calculate interval to approximate real-time playback speed
    frame_interval_ms = (hop_size / fs) * 1000

    ani = FuncAnimation(
        fig, 
        update, 
        frames=num_frames, 
        interval=frame_interval_ms, 
        blit=True,
        repeat=False
    )
    
    plt.tight_layout()
    plt.show()

# To run it, replace the execution call in your framework file with:
# dft_visualizer_strip.render_wav_animation("LOOPsTwo.wav")