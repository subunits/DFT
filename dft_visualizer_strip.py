#!/usr/bin/env python3
"""
Lightweight matplotlib-based DFT audio visualization without GUI framework.
Designed for rapid prototyping and headless analysis environments.
"""

import sys
import wave
from dataclasses import dataclass
from typing import Optional

import numpy as np
import scipy.fftpack as fftpack
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation


@dataclass
class AudioAnalysisConfig:
    """Configuration for audio analysis parameters."""
    window_size: int = 2048
    hop_size: int = 512
    onset_threshold: float = 0.15
    min_frequency_hz: float = 20.0
    max_peaks: int = 3
    spectrum_xlim: int = 4000
    spectrum_ylim: int = 50
    db_floor: float = 40.0


class NativeAudioSource:
    """Direct WAV file parser supporting 8/16/32-bit PCM formats."""

    DTYPE_MAP = {1: np.uint8, 2: np.int16, 4: np.int32}

    def __init__(self, filepath: str):
        self.wf = wave.open(filepath, "rb")
        self.sample_rate = self.wf.getframerate()
        self.channels = self.wf.getnchannels()
        self.sampwidth = self.wf.getsampwidth()
        self.n_frames = self.wf.getnframes()

        if self.sampwidth not in self.DTYPE_MAP:
            raise ValueError(
                f"Unsupported sample width: {self.sampwidth} bytes"
            )

    def read_all(self) -> np.ndarray:
        """Load entire WAV file and normalize to [-1.0, 1.0]."""
        raw_bytes = self.wf.readframes(self.n_frames)
        dtype = self.DTYPE_MAP[self.sampwidth]

        data = np.frombuffer(raw_bytes, dtype=dtype).astype(np.float32)

        # Normalize based on sample width
        if self.sampwidth == 1:
            data = (data - 128.0) / 128.0
        elif self.sampwidth == 2:
            data = data / 32768.0
        elif self.sampwidth == 4:
            data = data / 2147483648.0

        # Stereo downmix
        if self.channels > 1:
            data = data.reshape(-1, self.channels)
            data = np.mean(data, axis=1)

        return data

    def close(self) -> None:
        """Release file handle."""
        self.wf.close()


def render_wav_animation(
    filepath: str, config: Optional[AudioAnalysisConfig] = None
) -> None:
    """Animate real-time DFT analysis of WAV file."""
    config = config or AudioAnalysisConfig()

    try:
        source = NativeAudioSource(filepath)
        fs = source.sample_rate
        full_signal = source.read_all()
        source.close()
    except Exception as e:
        print(f"Error loading WAV file '{filepath}': {e}")
        return

    # Validate analysis window
    if config.window_size > len(full_signal):
        print(f"Window size {config.window_size} exceeds signal length")
        return

    fig, (ax_time, ax_freq) = plt.subplots(2, 1, figsize=(10, 7))

    line_time, = ax_time.plot([], [], color="g", linewidth=0.5)
    line_freq, = ax_freq.plot([], [], color="c", linewidth=1)

    ax_time.set_title("Time Domain Oscilloscope")
    ax_time.set_ylim(-1.0, 1.0)
    ax_time.set_xlim(0, config.window_size)
    ax_time.grid(True, alpha=0.3)

    ax_freq.set_title("DFT Spectrum Magnitude Analysis")
    ax_freq.set_xlim(0, config.spectrum_xlim)
    ax_freq.set_ylim(0, config.spectrum_ylim)
    ax_freq.set_xlabel("Frequency (Hz)")
    ax_freq.set_ylabel("Magnitude (dB)")
    ax_freq.grid(True, alpha=0.3)

    # Pre-compute constants
    freqs = np.fft.fftfreq(config.window_size, 1.0 / fs)[
        : config.window_size // 2
    ]
    hann_window = np.hanning(config.window_size)
    frame_interval_ms = (config.hop_size / fs) * 1000
    num_frames = (len(full_signal) - config.window_size) // config.hop_size

    annotations = []
    threshold_value = config.onset_threshold * 50.0

    def update(frame_idx: int) -> list:
        """Update plots for current frame."""
        # Clear previous annotations
        for anno in annotations:
            anno.remove()
        annotations.clear()

        # Extract frame
        start_idx = frame_idx * config.hop_size
        end_idx = start_idx + config.window_size
        chunk = full_signal[start_idx:end_idx]

        current_time = start_idx / fs
        fig.suptitle(
            f"DFT Analysis: {filepath} | Time: {current_time:.2f}s",
            fontsize=12,
        )

        # Time domain
        line_time.set_data(np.arange(config.window_size), chunk)

        # Frequency domain
        windowed = chunk * hann_window
        fft_complex = fftpack.fft(windowed)
        fft_mag = np.abs(fft_complex[: config.window_size // 2]) / (
            config.window_size / 2
        )
        fft_mag_db = 20 * np.log10(fft_mag + 1e-5) + config.db_floor

        line_freq.set_data(freqs, fft_mag_db)

        # Peak detection
        peak_indices = []
        for i in range(1, len(fft_mag_db) - 1):
            if (
                fft_mag_db[i] > fft_mag_db[i - 1]
                and fft_mag_db[i] > fft_mag_db[i + 1]
                and fft_mag_db[i] > threshold_value
                and freqs[i] >= config.min_frequency_hz
            ):
                peak_indices.append(i)

        # Keep highest peaks
        peak_indices.sort(
            key=lambda i: fft_mag_db[i], reverse=True
        )[: config.max_peaks]

        for idx in peak_indices:
            freq = freqs[idx]
            mag = fft_mag_db[idx]
            anno = ax_freq.annotate(
                f"{freq:.0f} Hz",
                xy=(freq, mag),
                xytext=(freq, mag + 3),
                arrowprops=dict(arrowstyle="->", color="y"),
                color="y",
                ha="center",
            )
            annotations.append(anno)

        return [line_time, line_freq] + annotations

    ani = FuncAnimation(
        fig,
        update,
        frames=num_frames,
        interval=frame_interval_ms,
        blit=True,
        repeat=False,
    )

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python dft_visualizer_strip.py <wav_file>")
        sys.exit(1)

    render_wav_animation(sys.argv[1])
