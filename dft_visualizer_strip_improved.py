#!/usr/bin/env python3
"""
File Name: dft_visualizer_strip_improved.py
Version: 2.1-ENHANCED

Lightweight matplotlib-based DFT audio visualization without GUI framework.
Designed for rapid prototyping and headless analysis environments.

Improvements over v2.0:
- Corrected FFT magnitude normalization for Hann window
- Input validation and error handling
- Logging support for diagnostics
- Performance optimizations (scipy peak detection)
- Better config validation
"""

import sys
import wave
import logging
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
import scipy.fftpack as fftpack
import scipy.signal as signal
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class AudioAnalysisConfig:
    """Configuration for audio analysis parameters."""
    window_size: int = 2048
    hop_size: int = 512
    onset_threshold: float = 0.15
    min_frequency_hz: float = 20.0
    max_frequency_hz: float = 20000.0  # NEW: Max frequency limit
    max_peaks: int = 3
    spectrum_xlim: int = 4000
    spectrum_ylim: int = 50
    db_floor: float = 40.0
    
    def __post_init__(self):
        """Validate configuration parameters."""
        if self.window_size < 256 or self.window_size > 16384:
            raise ValueError("window_size must be between 256 and 16384")
        
        if self.hop_size <= 0 or self.hop_size > self.window_size:
            raise ValueError("hop_size must be > 0 and <= window_size")
        
        if not (0.0 <= self.onset_threshold <= 1.0):
            raise ValueError("onset_threshold must be between 0 and 1")
        
        if self.min_frequency_hz < 0:
            raise ValueError("min_frequency_hz must be >= 0")
        
        if self.max_frequency_hz <= self.min_frequency_hz:
            raise ValueError("max_frequency_hz must be > min_frequency_hz")
        
        if self.max_peaks < 1:
            raise ValueError("max_peaks must be >= 1")


class NativeAudioSource:
    """Direct WAV file parser supporting 8/16/32-bit PCM formats."""

    DTYPE_MAP = {1: np.uint8, 2: np.int16, 4: np.int32}

    def __init__(self, filepath: str):
        # Validate file exists
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"Audio file not found: {filepath}")
        
        try:
            self.wf = wave.open(filepath, "rb")
        except Exception as e:
            raise ValueError(f"Failed to open WAV file: {e}")
        
        self.sample_rate = self.wf.getframerate()
        self.channels = self.wf.getnchannels()
        self.sampwidth = self.wf.getsampwidth()
        self.n_frames = self.wf.getnframes()
        self.filepath = filepath

        # Validate sample width
        if self.sampwidth not in self.DTYPE_MAP:
            raise ValueError(
                f"Unsupported sample width: {self.sampwidth} bytes. "
                f"Supported: 1, 2, or 4 bytes."
            )
        
        # Validate sample rate
        if self.sample_rate < 8000 or self.sample_rate > 192000:
            raise ValueError(f"Unsupported sample rate: {self.sample_rate} Hz")
        
        logger.info(
            f"Loaded WAV file: {filepath} | "
            f"SR: {self.sample_rate}Hz | "
            f"Channels: {self.channels} | "
            f"Sample width: {self.sampwidth} bytes | "
            f"Duration: {self.n_frames/self.sample_rate:.2f}s"
        )

    def read_all(self) -> np.ndarray:
        """Load entire WAV file and normalize to [-1.0, 1.0]."""
        try:
            raw_bytes = self.wf.readframes(self.n_frames)
        except Exception as e:
            raise ValueError(f"Failed to read audio frames: {e}")
        
        dtype = self.DTYPE_MAP[self.sampwidth]
        data = np.frombuffer(raw_bytes, dtype=dtype).astype(np.float32)

        # Normalize based on sample width
        if self.sampwidth == 1:
            data = (data - 128.0) / 128.0
        elif self.sampwidth == 2:
            data = data / 32768.0
        elif self.sampwidth == 4:
            data = data / 2147483648.0

        # Stereo downmix to mono
        if self.channels > 1:
            data = data.reshape(-1, self.channels)
            data = np.mean(data, axis=1)
            logger.info(f"Downmixed {self.channels} channels to mono")

        return data

    def close(self) -> None:
        """Release file handle."""
        if hasattr(self, 'wf') and self.wf:
            try:
                self.wf.close()
                logger.info(f"Closed audio file: {self.filepath}")
            except Exception as e:
                logger.error(f"Error closing audio file: {e}")


def render_wav_animation(
    filepath: str, config: Optional[AudioAnalysisConfig] = None
) -> None:
    """Animate real-time DFT analysis of WAV file.
    
    Args:
        filepath: Path to WAV file to analyze
        config: AudioAnalysisConfig object or None for defaults
        
    Raises:
        FileNotFoundError: If WAV file doesn't exist
        ValueError: If audio format is not supported
    """
    config = config or AudioAnalysisConfig()
    
    # Validate config
    try:
        # Post-init validation runs automatically via dataclass
        pass
    except ValueError as e:
        logger.error(f"Invalid configuration: {e}")
        raise

    try:
        source = NativeAudioSource(filepath)
        fs = source.sample_rate
        full_signal = source.read_all()
        source.close()
    except Exception as e:
        logger.error(f"Error loading WAV file '{filepath}': {e}")
        raise

    # Validate analysis window
    if config.window_size > len(full_signal):
        raise ValueError(
            f"Window size ({config.window_size}) exceeds signal length ({len(full_signal)}). "
            f"Try reducing window_size or using a longer audio file."
        )

    logger.info(
        f"Starting animation: window={config.window_size}, "
        f"hop={config.hop_size}, threshold={config.onset_threshold}"
    )

    fig, (ax_time, ax_freq) = plt.subplots(2, 1, figsize=(10, 7))

    line_time, = ax_time.plot([], [], color="g", linewidth=0.5)
    line_freq, = ax_freq.plot([], [], color="c", linewidth=1)

    ax_time.set_title("Time Domain Oscilloscope")
    ax_time.set_ylim(-1.0, 1.0)
    ax_time.set_xlim(0, config.window_size)
    ax_time.set_ylabel("Amplitude")
    ax_time.set_xlabel("Samples")
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
    
    # NEW: Compute window normalization factor
    window_norm = np.sum(hann_window) / len(hann_window)
    
    frame_interval_ms = (config.hop_size / fs) * 1000
    num_frames = (len(full_signal) - config.window_size) // config.hop_size

    if num_frames <= 0:
        raise ValueError(
            f"Not enough samples for analysis. "
            f"Need at least {config.window_size + config.hop_size} samples, "
            f"got {len(full_signal)}."
        )

    annotations = []
    threshold_value = config.onset_threshold * 50.0

    logger.info(f"Analyzing {num_frames} frames at {frame_interval_ms:.1f}ms intervals")

    def update(frame_idx: int) -> list:
        """Update plots for current frame."""
        # Clear previous annotations
        for anno in annotations:
            try:
                anno.remove()
            except Exception:
                pass
        annotations.clear()

        # Extract frame
        start_idx = frame_idx * config.hop_size
        end_idx = start_idx + config.window_size
        chunk = full_signal[start_idx:end_idx]

        current_time = start_idx / fs
        fig.suptitle(
            f"DFT Analysis: {os.path.basename(filepath)} | "
            f"Time: {current_time:.2f}s | Frame: {frame_idx}/{num_frames}",
            fontsize=12,
        )

        # Time domain
        line_time.set_data(np.arange(config.window_size), chunk)

        # Frequency domain
        windowed = chunk * hann_window
        
        # NEW: Corrected normalization
        fft_complex = fftpack.fft(windowed)
        fft_mag = np.abs(fft_complex[: config.window_size // 2]) / (
            config.window_size * window_norm / 2
        )
        fft_mag_db = 20 * np.log10(fft_mag + 1e-5) + config.db_floor

        line_freq.set_data(freqs, fft_mag_db)

        # Peak detection - NEW: Use scipy.signal.find_peaks for efficiency
        try:
            # Find peaks above threshold
            peak_indices, properties = signal.find_peaks(
                fft_mag_db,
                height=threshold_value,
                distance=2  # Minimum separation between peaks
            )
            
            # Filter by frequency range
            peak_indices = peak_indices[
                (freqs[peak_indices] >= config.min_frequency_hz) &
                (freqs[peak_indices] <= config.max_frequency_hz)
            ]
            
            # Keep highest magnitude peaks
            if len(peak_indices) > 0:
                heights = fft_mag_db[peak_indices]
                peak_indices = peak_indices[
                    np.argsort(heights)[-config.max_peaks:][::-1]
                ]
        except Exception as e:
            logger.warning(f"Peak detection error on frame {frame_idx}: {e}")
            peak_indices = []

        # Annotate peaks
        for idx in peak_indices:
            freq = freqs[idx]
            mag = fft_mag_db[idx]
            try:
                anno = ax_freq.annotate(
                    f"{freq:.0f} Hz",
                    xy=(freq, mag),
                    xytext=(freq, mag + 3),
                    arrowprops=dict(arrowstyle="->", color="y", lw=1),
                    color="y",
                    ha="center",
                    fontsize=9,
                )
                annotations.append(anno)
            except Exception as e:
                logger.warning(f"Failed to annotate peak at {freq:.0f} Hz: {e}")

        return [line_time, line_freq] + annotations

    # Create animation
    ani = FuncAnimation(
        fig,
        update,
        frames=num_frames,
        interval=frame_interval_ms,
        blit=True,
        repeat=False,
    )

    plt.tight_layout()
    logger.info("Animation started. Close window to exit.")
    
    try:
        plt.show()
    except KeyboardInterrupt:
        logger.info("Animation interrupted by user")
    except Exception as e:
        logger.error(f"Animation error: {e}")
        raise
    finally:
        logger.info("Animation finished")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python dft_visualizer_strip.py <wav_file>")
        print("\nExample:")
        print("  python dft_visualizer_strip.py audio.wav")
        sys.exit(1)

    try:
        wav_file = sys.argv[1]
        render_wav_animation(wav_file)
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        sys.exit(1)
    except ValueError as e:
        logger.error(f"Invalid audio file: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
