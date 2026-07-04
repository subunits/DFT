# Developer Quick Reference

## Code Organization

### Core Classes

#### **CircularAudioBuffer**
```python
buffer = CircularAudioBuffer(size=8192)
buffer.extend(new_data)              # Add samples (O(1))
ordered = buffer.get_ordered_window() # Get chronological view
```

**Why**: Avoids expensive np.roll() operations. Maintains O(1) time complexity.

---

#### **LiveAudioSource** (Real-time capture)
```python
source = LiveAudioSource(max_queue_size=500)
source.start_capture(sample_rate=44100)
block = source.read()        # Non-blocking, returns array or []
source.stop_capture()
```

**Thread Model**: 
- Callback thread (sounddevice) → queue → main UI thread
- Prevents audio capture from blocking rendering

**Queue Behavior**:
- On overflow: Drops oldest frame (live input, ok to lose one frame)
- On empty: Returns empty array (UI skips that frame)

---

#### **FileAudioSource** (Time-synchronized playback)
```python
source = FileAudioSource("audio.wav", block_size=1024, max_sleep_ms=5.0)
sample_rate = source.sample_rate
block = source.read()  # Returns array, [] when finished
source.close()         # Must release file handle
```

**Sync Mechanism**:
```
Expected time = frames_read / sample_rate
Actual time = time.perf_counter() - start_time

if expected > actual:
    sleep(expected - actual)  # Slow down playback
```

---

#### **DFTVisualizer** (Main UI)
```python
app = DFTVisualizer(
    audio_config=AudioConfig(...),
    viz_config=VisualizerConfig(...),
    audio_filepath=None  # None = live, else path to file
)
app.show()
```

**Key Methods**:
- `_init_ui()`: Build PyQtGraph layout
- `_init_audio()`: Setup audio source
- `_update_frame()`: Main DSP loop (called 60× per second)
- `closeEvent()`: Cleanup on window close

---

## Signal Processing Pipeline

### FFT + Windowing
```python
# 1. Extract window from circular buffer
window = buffer.get_ordered_window()[-2048:]

# 2. Apply Hann windowing (reduces spectral leakage)
hann = np.hanning(len(window))
windowed = window * hann

# 3. Compute FFT
fft = scipy.fftpack.fft(windowed)

# 4. Convert to magnitude (dB scale)
mag = np.abs(fft[:len(window)//2]) / (len(window) / 2)
mag_db = 20 * np.log10(mag + 1e-5) + 40  # +40 dB floor
```

**Why Hann window?**
- Reduces spectral leakage (side lobes from non-integer-period signals)
- Trade-off: Slightly widens peak width (~4 Hz for 2048@44.1kHz)
- Alternative: Blackman, Hamming (trade main lobe width vs. side lobe level)

---

### Peak Detection
```python
threshold = 0.15 * 50  # User slider (0-1) → dB scale (0-50)

for i in range(1, len(mag_db) - 1):
    is_local_max = (mag_db[i] > mag_db[i-1]) and (mag_db[i] > mag_db[i+1])
    is_above_threshold = mag_db[i] > threshold
    is_audible = frequencies[i] >= 20  # Hz
    
    if is_local_max and is_above_threshold and is_audible:
        peaks.append(i)

# Sort by magnitude and keep top 3
peaks = sorted(peaks, key=lambda i: mag_db[i])[-3:]
```

---

## Modifying the Code

### Add a New Window Function

**dft_visualizer.py**:
```python
import enum

class WindowType(enum.Enum):
    HANN = "hann"
    BLACKMAN = "blackman"
    HAMMING = "hamming"

class AudioConfig:
    window_function: WindowType = WindowType.HANN

# In _update_frame():
if self.audio_config.window_function == WindowType.HANN:
    window = np.hanning(len(display_window))
elif self.audio_config.window_function == WindowType.BLACKMAN:
    window = np.blackman(len(display_window))
else:
    window = np.hamming(len(display_window))
```

---

### Add Frequency Axis Labeling

**dft_visualizer.py**:
```python
# In _init_ui(), after creating spectrum_plot_view:
self.spectrum_plot_view.setLabel('bottom', 'Frequency', units='Hz')
self.spectrum_plot_view.setLabel('left', 'Magnitude', units='dB')

# Add frequency tick marks
ax = self.spectrum_plot_view.getAxis('bottom')
ax.setTicks([
    [(0, '0'), (1000, '1k'), (5000, '5k'), (10000, '10k'), (20000, '20k')],
    []  # Major ticks
])
```

---

### Export Spectrogram Data

```python
# Store analysis data
class SpectrogramRecorder:
    def __init__(self, hop_size, sample_rate):
        self.frames = []
        self.hop_size = hop_size
        self.sample_rate = sample_rate
    
    def add_frame(self, frequencies, magnitude_db):
        self.frames.append((frequencies, magnitude_db.copy()))
    
    def export_csv(self, filename):
        import csv
        with open(filename, 'w') as f:
            writer = csv.writer(f)
            writer.writerow(['Time_s', 'Freq_Hz', 'Mag_dB'])
            
            for frame_idx, (freqs, mags) in enumerate(self.frames):
                time_s = (frame_idx * self.hop_size) / self.sample_rate
                for freq, mag in zip(freqs, mags):
                    writer.writerow([time_s, freq, mag])

# Usage:
recorder = SpectrogramRecorder(hop_size=512, sample_rate=44100)
# In _update_frame(), after computing FFT:
recorder.add_frame(frequencies, fft_mag_db)
# On close:
recorder.export_csv("spectrogram.csv")
```

---

## Common Issues & Solutions

### Issue: Audio Capture is Silent
```python
# Debug: Check if audio is entering the queue
source = LiveAudioSource()
source.start_capture(44100)
time.sleep(0.1)

while True:
    block = source.read()
    if len(block) > 0:
        print(f"Captured {len(block)} samples, peak: {np.max(np.abs(block)):.3f}")
        break
    time.sleep(0.01)
```

### Issue: FFT Looks Wrong
```python
# Common mistake: Forgetting window normalization
# BAD:
mag = np.abs(fft[:n//2]) / (n / 2)

# GOOD: Account for window energy loss
window_correction = np.sum(window) / len(window)
mag = np.abs(fft[:n//2]) / (n * window_correction / 2)
```

### Issue: Peaks Not Appearing
```python
# Check threshold calculation
print(f"Current threshold: {self.onset_threshold} (0-1)")
print(f"dB threshold: {self.onset_threshold * 50} dB")
print(f"Max mag in spectrum: {np.max(mag_db)} dB")

# Increase sensitivity (move slider left) if max < threshold
```

---

## Testing

### Unit Test Template

```python
import unittest
import numpy as np
from dft_visualizer import CircularAudioBuffer

class TestCircularBuffer(unittest.TestCase):
    def test_basic_extend(self):
        buf = CircularAudioBuffer(size=10)
        buf.extend(np.array([1, 2, 3], dtype=np.float32))
        
        ordered = buf.get_ordered_window()
        np.testing.assert_array_equal(ordered[:3], [1, 2, 3])
    
    def test_wraparound(self):
        buf = CircularAudioBuffer(size=10)
        buf.extend(np.arange(15, dtype=np.float32))  # Larger than buffer
        
        ordered = buf.get_ordered_window()
        # Should contain last 10 elements (5-14)
        np.testing.assert_array_equal(ordered, np.arange(5, 15, dtype=np.float32))
    
    def test_o1_complexity(self):
        # Verify no data copying on each extend
        buf = CircularAudioBuffer(size=8192)
        
        import time
        start = time.perf_counter()
        for _ in range(1000):
            buf.extend(np.random.randn(1024).astype(np.float32))
        elapsed = time.perf_counter() - start
        
        # Should be < 100ms for 1000 extends
        self.assertLess(elapsed, 0.1)

if __name__ == '__main__':
    unittest.main()
```

---

## Performance Tuning

| Parameter | Smaller = | Larger = |
|-----------|-----------|----------|
| `window_size` | ↑ Time resolution, ↓ Freq resolution | ↓ Time res, ↑ Freq res |
| `hop_size` | ↑ Frame rate, ↑ CPU | ↓ Frame rate, ↓ CPU |
| `buffer_size` | ↓ Memory, ↓ history | ↑ Memory, ↑ history |
| `frame_interval_ms` | ↑ CPU, Smoother | ↓ CPU, Choppier |

**Recommended starting points**:
- Music: `window_size=4096`, `hop_size=1024` (44.1kHz)
- Speech: `window_size=2048`, `hop_size=512` (44.1kHz)
- Low-latency: `window_size=1024`, `hop_size=256` (48kHz)

---

## Dependencies Version Check

```python
import numpy
import scipy
import PyQt5
import pyqtgraph
import sounddevice
import soundfile

print(f"NumPy: {numpy.__version__}")
print(f"SciPy: {scipy.__version__}")
print(f"PyQt5: {PyQt5.__version__}")
print(f"pyqtgraph: {pyqtgraph.__version__}")
print(f"sounddevice: {sounddevice.__version__}")
print(f"soundfile: {soundfile.__version__}")
```

Minimum versions:
- NumPy 1.19+
- SciPy 1.5+
- PyQt5 5.12+
- pyqtgraph 0.11+
- sounddevice 0.4+
- soundfile 0.10+

---

## Debug Mode

Add to top of file:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# In callbacks/loops:
logger.debug(f"Queue size: {self.audio_source.audio_queue.qsize()}")
logger.debug(f"Frame latency: {self.frame_time:.1f}ms")
logger.debug(f"FFT peaks: {peak_frequencies}")
```

---

## Architecture Diagram

```
User Input (Slider)
    ↓
┌───────────────────────────┐
│  _on_threshold_changed()  │  Updates onset_threshold
└───────────────────────────┘
    ↓
┌───────────────────────────────────────────┐
│       _update_frame() [60 Hz loop]        │
├───────────────────────────────────────────┤
│ 1. Read from audio_source.read()          │
│ 2. Extend CircularAudioBuffer             │
│ 3. Window + FFT (SciPy)                   │
│ 4. Magnitude → dB scale                   │
│ 5. Detect peaks                           │
│ 6. Update PyQtGraph plots                 │
└───────────────────────────────────────────┘
    ↓              ↓              ↓
Waveform Plot  Spectrum Plot  Peak Labels
```

---

**Last Updated**: July 2024
