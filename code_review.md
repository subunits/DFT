# DFT Audio Visualizer - Code Review (v3.1)

## ✅ STRENGTHS

1. **Graceful PyQt5/6 Compatibility** - Good fallback handling for different Qt versions
2. **Thread Safety** - Uses locks for shared buffers (audio buffer, recorder)
3. **Robust Onset Detection** - Warmup frames prevent false positives
4. **Resource Cleanup** - closeEvent() properly stops timers and streams
5. **Signal Window Options** - Variety of windowing functions (Hann, Hamming, Blackman)
6. **Musical Note Mapping** - Accurate frequency-to-MIDI-to-note conversion
7. **Preset System** - Save/load functionality via JSON

---

## ⚠️ CRITICAL ISSUES

### 1. **File Playback Timing Bug** (FileAudioSource)
**Location:** Line ~224-245
```python
if actual_elapsed < expected_elapsed:
    return None
```
**Problem:** Returns None when timing is off, causing audio to stutter and gaps in visualization.
**Impact:** File mode unreliable for real-time playback.
**Fix:** Use proper buffering or re-design timing logic.

### 2. **Memory Leak in Peak Detection Labels**
**Location:** Line ~640-651
```python
for it in self.peak_text_items:
    self.plot_widget.removeItem(it)
self.peak_text_items = []
```
**Problem:** If `removeItem()` fails, stale references accumulate. No exception handling.
**Potential Issue:** Over many hours, memory usage could creep up.

### 3. **Unprotected Spectrogram Resize**
**Location:** Line ~563-567 (_recalc_freqs)
```python
self.sgram = np.full((self.freqs.size, self.spec_len), ...)
```
**Problem:** If FFT size changes mid-frame, spectral data could be misaligned. No locking around buffer access.
**Impact:** Potential crash or visual glitches when changing FFT size during active audio.

### 4. **No Device Selection for Live Audio**
**Location:** Line ~277
```python
self.stream = sd.InputStream(..., device=device)
```
**Problem:** `device=None` defaults to system default, but no UI to select different devices.
**Impact:** Users with multiple audio inputs can't switch without CLI args.

---

## 🔴 MODERATE CONCERNS

### 5. **Race Condition on Window Close**
**Location:** closeEvent() vs. _on_timer()
**Problem:** 
- Timer fires simultaneously with window close
- Audio source close and timer stop could race
- Recorder stop and push could interleave

**Fix:** Use a stopped flag checked in _on_timer:
```python
self.is_closing = False  # in __init__
# in closeEvent:
self.is_closing = True
self.timer.stop()  # before other cleanup
# in _on_timer:
if self.is_closing:
    return
```

### 6. **Buffer Overflow in LiveAudioSource**
**Location:** Line ~309-312
```python
while len(self.buffer) > 200:
    self.buffer.popleft()
```
**Problem:** Hard-coded limit of 200 blocks (~2.3s at 44.1kHz/1024hop). No feedback to user if buffer overflows.
**Impact:** Drops audio silently if GUI can't keep up.

### 7. **FFT Size / Hop Size Validation**
**Location:** Line ~178
```python
self.hop = max(MIN_HOP, min(hop, fft_size))
```
**Problem:** No validation that hop is sensible (e.g., hop < fft_size is clamped, but no warning).
**Better:** Enforce hop ≤ fft_size with explicit error.

### 8. **Colormap Error Silently Ignored**
**Location:** Line ~476
```python
except Exception as e:
    print("Could not apply colormap:", e, file=sys.stderr)
```
**Problem:** If colormap fails, visualization still renders with default. No fallback.
**Fix:** Validate colormap name exists or provide safe default.

### 9. **Snapshot Export Failure Silent**
**Location:** Line ~615
```python
except Exception as e:
    print(f"Error saving snapshot...")
```
**Problem:** User sees button clicked, but no feedback if it fails. No success message either.
**Fix:** Add status bar or dialog popup.

---

## 🟡 DESIGN / MAINTAINABILITY ISSUES

### 10. **Hardcoded Audio Stream Parameters**
- Sample rate: 44.1 kHz (good default, but no UI control)
- Block size coupling: hop size = read block size (inflexible)
- Buffer size: 200 blocks (magic number)

### 11. **No Logging / Debugging**
- Critical errors print to stderr, success to stdout (inconsistent)
- No timestamps on messages
- No option to log to file

### 12. **Numpy Array Inefficiency**
**Location:** Line ~622
```python
self.sgram = np.roll(self.sgram, -1, axis=1)
self.sgram[:, -1] = mag_db
```
**Problem:** Roll allocates new array every frame. For 300-frame history, this is wasteful.
**Better:** Use circular buffer index:
```python
self.sgram_idx = (self.sgram_idx + 1) % self.spec_len
self.sgram[:, self.sgram_idx] = mag_db
```

### 13. **No Bounds Check on Peak Detection**
**Location:** Line ~608
```python
if f <= 0:
    return  # <-- returns from entire loop!
```
**Problem:** `return` exits _on_timer() entirely, skipping spectrogram update and peak display.
**Fix:** Use `continue` to skip just that peak.

### 14. **Onset Threshold Not Exposed in UI**
**Location:** Line ~407
```python
self.onset_thr = 4.0
```
**Problem:** Fixed value, no slider. Users can't tune onset sensitivity.

### 15. **Recording Quality Coupling**
**Location:** Line ~241
```python
sf.write(self.outpath, buf, self.sr)
```
**Problem:** Always writes PCM (no compression). No bitrate/format options.

---

## 🟢 MINOR NITPICKS

### 16. Window Combo Duplicate Entries
If loading a preset with an unknown window name, it won't be added to combo.

### 17. File Extension Checking
No validation that file argument is actually an audio file before loading.

### 18. Magic Numbers
- `interval = max(5, int(...) // 2)` – unclear why divide by 2
- `self.onset_flash_timer.start(120)` – 120ms flash duration, not configurable
- `warmup_frames=8` in OnsetDetector – not exposed

### 19. Peak Text Anchoring
Text labels have hardcoded anchor `(0.5, 1.0)` – could overlap if many peaks close together.

### 20. No Peak Count Bounds
User can set peak_count to 0 or negative (via preset file tampering).

---

## SUMMARY TABLE

| Issue | Severity | Impact | Fix Effort |
|-------|----------|--------|-----------|
| File playback timing | Critical | Broken file mode | Medium |
| Peak label memory leak | Moderate | Gradual leak | Low |
| Spectrogram resize race | Moderate | Crash potential | Medium |
| Window close race | Moderate | Rare crash | Low |
| Buffer overflow silent | Moderate | Audio loss | Low |
| Peak detection return bug | Moderate | Skips spectrogram | Low |
| Circular buffer inefficiency | Minor | CPU waste | Low |
| Missing device selection | Minor | UX limitation | Low |

