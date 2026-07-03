#!/usr/bin/env python3
"""
File Name: dft_visualizer.py
Version: 4.0-REFACTORED

Enterprise-grade real-time DFT audio visualizer with O(1) circular buffering,
thread-safe async queueing, and memory-efficient PyQtGraph rendering.
"""

import sys
import time
import queue
from dataclasses import dataclass
from typing import Optional

import numpy as np
import scipy.fftpack as fftpack
from PyQt5 import QtCore, QtWidgets
import pyqtgraph as pg
import sounddevice as sd
import soundfile as sf


@dataclass
class AudioConfig:
    """Audio processing configuration parameters."""
    sample_rate: int = 44100
    window_size: int = 2048
    buffer_size: int = 8192
    block_size: int = 1024
    frame_interval_ms: int = 16
    max_sleep_ms: float = 5.0


@dataclass
class VisualizerConfig:
    """Visualizer UI configuration parameters."""
    waveform_range: tuple = (-1.0, 1.0)
    spectrum_range: tuple = (0, 50)
    db_floor: float = 40.0
    min_frequency_hz: float = 20.0
    max_peaks_displayed: int = 3
    onset_threshold_default: float = 0.15


class CircularAudioBuffer:
    """O(1) circular buffer with chronological ordering capability."""

    def __init__(self, size: int, dtype: np.dtype = np.float32):
        self.size = size
        self.buffer = np.zeros(size, dtype=dtype)
        self.write_index = 0

    def extend(self, data: np.ndarray) -> None:
        """Append new data using circular pointer arithmetic."""
        if len(data) == 0:
            return

        if len(data) >= self.size:
            self.buffer[:] = data[-self.size :]
            self.write_index = 0
            return

        remaining_space = self.size - self.write_index
        
        if len(data) <= remaining_space:
            self.buffer[self.write_index : self.write_index + len(data)] = data
            self.write_index = (self.write_index + len(data)) % self.size
        else:
            self.buffer[self.write_index :] = data[:remaining_space]
            self.buffer[: len(data) - remaining_space] = data[remaining_space:]
            self.write_index = len(data) - remaining_space

    def get_ordered_window(self) -> np.ndarray:
        """Return buffer contents in chronological order."""
        if self.write_index == 0:
            return self.buffer.copy()
        return np.concatenate(
            (self.buffer[self.write_index :], self.buffer[: self.write_index])
        )


class LiveAudioSource:
    """Thread-safe queue-based live audio ingestion."""

    def __init__(self, max_queue_size: int = 500):
        self.audio_queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self.sample_rate: int = 44100
        self.is_active: bool = False

    def callback(
        self, indata: np.ndarray, frames: int, time_info, status
    ) -> None:
        """System audio callback routing samples to queue."""
        if status:
            return

        try:
            data = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
            self.audio_queue.put_nowait(data)
        except queue.Full:
            try:
                self.audio_queue.get_nowait()
                self.audio_queue.put_nowait(data)
            except (queue.Empty, queue.Full):
                pass

    def read(self) -> np.ndarray:
        """Read next audio block or return empty array."""
        try:
            return self.audio_queue.get_nowait()
        except queue.Empty:
            return np.array([], dtype=np.float32)

    def start_capture(self, sample_rate: int) -> None:
        """Initialize hardware audio stream."""
        self.sample_rate = sample_rate
        self.stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            blocksize=1024,
            callback=self.callback,
        )
        self.stream.start()
        self.is_active = True

    def stop_capture(self) -> None:
        """Safely close hardware audio stream."""
        if hasattr(self, "stream"):
            self.stream.stop()
            self.stream.close()
            self.is_active = False


class FileAudioSource:
    """Time-synchronized file playback with adaptive micro-sleeping."""

    def __init__(self, filepath: str, block_size: int = 1024, max_sleep_ms: float = 5.0):
        self.file = sf.SoundFile(filepath)
        self.block_size = block_size
        self.max_sleep_sec = max_sleep_ms / 1000.0
        self.sample_rate = self.file.samplerate
        self.start_time = time.perf_counter()
        self.frames_read = 0

    def read(self) -> np.ndarray:
        """Read time-synced block with micro-sleep pacing."""
        if self.frames_read >= self.file.frames:
            return np.array([], dtype=np.float32)

        expected_elapsed = self.frames_read / self.sample_rate
        actual_elapsed = time.perf_counter() - self.start_time

        if expected_elapsed > actual_elapsed:
            sleep_time = min(expected_elapsed - actual_elapsed, self.max_sleep_sec)
            time.sleep(sleep_time)
            return np.array([], dtype=np.float32)

        data = self.file.read(self.block_size, dtype="float32")
        if len(data) == 0:
            return np.array([], dtype=np.float32)

        if data.ndim > 1:
            data = np.mean(data, axis=1)

        self.frames_read += len(data)
        return data

    def close(self) -> None:
        """Release file resources."""
        if hasattr(self, "file") and self.file:
            self.file.close()


class DFTVisualizer(QtWidgets.QMainWindow):
    """Real-time audio DFT visualization with peak detection."""

    def __init__(self, audio_config: AudioConfig = None, viz_config: VisualizerConfig = None, audio_filepath: Optional[str] = None):
        super().__init__()
        
        self.audio_config = audio_config or AudioConfig()
        self.viz_config = viz_config or VisualizerConfig()
        self.audio_filepath = audio_filepath
        
        self.setWindowTitle("DFT Audio Visualizer v4.0")
        self.resize(1024, 700)

        self.audio_buffer = CircularAudioBuffer(self.audio_config.buffer_size)
        self.audio_source: Optional[LiveAudioSource | FileAudioSource] = None
        self.peak_text_items: list = []
        self.onset_threshold = self.viz_config.onset_threshold_default

        self._init_ui()
        self._init_audio()

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._update_frame)
        self.timer.start(self.audio_config.frame_interval_ms)

    def _init_ui(self) -> None:
        """Construct UI layout hierarchy."""
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)

        # Control panel
        control_layout = QtWidgets.QHBoxLayout()
        control_layout.addWidget(QtWidgets.QLabel("Peak Sensitivity:"))

        self.threshold_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.threshold_slider.setMinimum(1)
        self.threshold_slider.setMaximum(100)
        self.threshold_slider.setValue(
            int(self.viz_config.onset_threshold_default * 100)
        )
        self.threshold_slider.valueChanged.connect(self._on_threshold_changed)
        control_layout.addWidget(self.threshold_slider)
        main_layout.addLayout(control_layout)

        # PyQtGraph plots
        self.graphics_view = pg.GraphicsLayoutWidget()
        main_layout.addWidget(self.graphics_view)

        self.waveform_plot_view = self.graphics_view.addPlot(
            title="Time Domain Oscilloscope"
        )
        self.waveform_plot_view.setYRange(*self.viz_config.waveform_range)
        self.waveform_curve = self.waveform_plot_view.plot(pen="g")

        self.graphics_view.nextRow()

        self.spectrum_plot_view = self.graphics_view.addPlot(
            title="DFT Spectrum Magnitude"
        )
        self.spectrum_plot_view.setYRange(*self.viz_config.spectrum_range)
        self.spectrum_curve = self.spectrum_plot_view.plot(pen="c")

    def _init_audio(self) -> None:
        """Initialize audio source (file or live)."""
        if self.audio_filepath:
            try:
                self.audio_source = FileAudioSource(
                    self.audio_filepath,
                    block_size=self.audio_config.block_size,
                    max_sleep_ms=self.audio_config.max_sleep_ms,
                )
                self.audio_config.sample_rate = self.audio_source.sample_rate
                return
            except Exception as e:
                print(f"File load error: {e}. Falling back to microphone.")

        self.audio_source = LiveAudioSource()
        self.audio_source.start_capture(self.audio_config.sample_rate)

    def _on_threshold_changed(self, value: int) -> None:
        """Update onset threshold from slider."""
        self.onset_threshold = value / 100.0

    def _clear_peak_annotations(self) -> None:
        """Remove all peak text items from plot."""
        for item in self.peak_text_items:
            try:
                self.spectrum_plot_view.removeItem(item)
            except Exception:
                pass
        self.peak_text_items.clear()

    def _detect_peaks(self, magnitude_db: np.ndarray, frequencies: np.ndarray) -> None:
        """Detect and annotate local maxima in spectrum."""
        self._clear_peak_annotations()
        
        threshold_value = self.onset_threshold * 50.0
        peak_indices = []

        for i in range(1, len(magnitude_db) - 1):
            if (
                magnitude_db[i] > magnitude_db[i - 1]
                and magnitude_db[i] > magnitude_db[i + 1]
                and magnitude_db[i] > threshold_value
                and frequencies[i] >= self.viz_config.min_frequency_hz
            ):
                peak_indices.append(i)

        # Keep highest peaks
        peak_indices.sort(
            key=lambda i: magnitude_db[i], reverse=True
        )[: self.viz_config.max_peaks_displayed]

        for idx in peak_indices:
            freq = frequencies[idx]
            mag = magnitude_db[idx]
            text_item = pg.TextItem(
                text=f"{freq:.0f} Hz", color="y", anchor=(0.5, 1)
            )
            self.spectrum_plot_view.addItem(text_item)
            text_item.setPos(freq, mag + 2)
            self.peak_text_items.append(text_item)

    def _update_frame(self) -> None:
        """Main processing loop for frame updates."""
        raw_block = self.audio_source.read()

        if len(raw_block) == 0:
            return

        self.audio_buffer.extend(raw_block)
        ordered_data = self.audio_buffer.get_ordered_window()

        # Time domain display
        display_window = ordered_data[-self.audio_config.window_size :]
        self.waveform_curve.setData(display_window)

        # Frequency domain analysis
        hann_window = np.hanning(len(display_window))
        windowed_signal = display_window * hann_window

        fft_complex = fftpack.fft(windowed_signal)
        fft_mag = np.abs(fft_complex[: self.audio_config.window_size // 2]) / (
            self.audio_config.window_size / 2
        )
        fft_mag_db = (
            20 * np.log10(fft_mag + 1e-5) + self.viz_config.db_floor
        )

        frequencies = np.fft.fftfreq(
            self.audio_config.window_size, 1.0 / self.audio_config.sample_rate
        )[: self.audio_config.window_size // 2]

        self.spectrum_curve.setData(frequencies, fft_mag_db)
        self._detect_peaks(fft_mag_db, frequencies)

    def closeEvent(self, event) -> None:
        """Cleanup on window close."""
        self.timer.stop()
        if isinstance(self.audio_source, LiveAudioSource):
            self.audio_source.stop_capture()
        elif isinstance(self.audio_source, FileAudioSource):
            self.audio_source.close()
        self._clear_peak_annotations()
        event.accept()


if __name__ == "__main__":
    filepath = sys.argv[1] if len(sys.argv) > 1 else None

    app = QtWidgets.QApplication(sys.argv)
    visualizer = DFTVisualizer(audio_filepath=filepath)
    visualizer.show()

    sys.exit(app.exec_() if hasattr(app, "exec_") else app.exec())
