"""Pre-action screenshot verification for the playback engine.

Two responsibilities:

1. ``compare_screenshots`` — pure-function comparison of two PIL images
   using either pixel-diff or perceptual-hash metrics. No I/O, no
   threading. Importable from anywhere in the codebase.
2. ``verify_before_event`` — orchestrates the live-screen capture,
   expected-image decode, comparison, and on-fail callback for a single
   recorded event. The player calls this once per event in its loop
   instead of carrying the logic itself.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from PIL import Image, ImageChops

from .. import config
from ..data.models import Recording, RecordedEvent
from ..data.utils import base64_to_image, take_stable_screenshot
from .target_window import TargetWindow

# Type alias for the failure callback the player passes through.
OnVerificationFail = Callable[[RecordedEvent, str, Image.Image, Image.Image], None]
# Optional callback fired after every verification attempt (success or
# fail). Lets callers cache the live capture for UI display so step view
# and verification stay on the same baseline.
OnVerificationCapture = Callable[
    [RecordedEvent, Image.Image, Image.Image, str, bool], None
]


def compare_screenshots(
    live: Image.Image,
    expected: Image.Image,
    *,
    method: str = "pixel",
    tolerance_pct: float = 5.0,
    pixel_threshold: int = 16,
    phash_max_distance: int = 125,
) -> tuple[bool, float, str]:
    """Compare two screenshots, returning ``(passed, diff_value, diff_text)``.

    ``method`` selects the comparison strategy:

    * ``"pixel"`` — per-pixel max-channel delta. A pixel "differs" when its
      largest per-channel delta exceeds ``pixel_threshold`` (0–255). The
      result fails if more than ``tolerance_pct`` percent of pixels
      differ. ``diff_value`` is the % of changed pixels; ``diff_text`` is
      e.g. ``"3.21%"``.

    * ``"phash"`` — perceptual hash + Hamming distance. Returns
      ``passed`` if the 324-bit pHash distance is ``<= phash_max_distance``.
      ``diff_value`` is the integer Hamming distance; ``diff_text`` is
      e.g. ``"60 / 324 bits"``. Tolerant of compression/anti-aliasing
      jitter common over RDP, but coarser than pixel diff.

    Size mismatch is treated as an immediate failure for both methods —
    silently resizing would mask real drift such as window resize or DPI
    change. ``diff_text`` is ``"size mismatch"`` in that case.
    """
    if live.size != expected.size:
        # Use a method-specific "max" diff value so callers that compare
        # against a numeric threshold still see "way over".
        max_value = 100.0 if method == "pixel" else 324.0
        return False, max_value, "size mismatch"

    if method == "phash":
        # Lazy import — keeps imagehash optional for environments that
        # don't run verification.
        import imagehash
        # hash_size=18 → 18*18 = 324-bit fingerprint, giving ~5x more
        # resolution than the original 64-bit (hash_size=8) hash.
        h_live = imagehash.phash(live, hash_size=18)
        h_expected = imagehash.phash(expected, hash_size=18)
        distance = h_live - h_expected
        return (
            distance <= phash_max_distance,
            float(distance),
            f"{distance} / 324 bits",
        )

    if method != "pixel":
        # Unknown method → fall back to pixel diff rather than crash.
        method = "pixel"

    # Coerce to RGB so RGBA vs RGB doesn't add a bogus alpha-difference.
    a = live.convert("RGB")
    b = expected.convert("RGB")
    diff = ImageChops.difference(a, b)
    # Reduce RGB to a single max channel: a pixel "changed" when the
    # largest per-channel delta exceeds the threshold. Convert to "L"
    # mode using the max of (R, G, B).
    max_band = diff.getchannel(0)
    for ch in (1, 2):
        max_band = ImageChops.lighter(max_band, diff.getchannel(ch))
    # Count pixels above threshold via histogram (fast, no Python loop).
    hist = max_band.histogram()
    changed = sum(hist[pixel_threshold + 1:])
    total = max_band.width * max_band.height
    diff_pct = (changed / total * 100.0) if total else 0.0
    return diff_pct <= tolerance_pct, diff_pct, f"{diff_pct:.2f}%"


def verify_before_event(
    event: RecordedEvent,
    recording: Recording,
    target: Optional[TargetWindow],
    stop_flag: threading.Event,
    on_fail: Optional[OnVerificationFail] = None,
    on_capture: Optional[OnVerificationCapture] = None,
) -> bool:
    """Compare the live screen to ``event.before_screenshot``.

    Returns ``True`` if verification failed AND the configured policy is
    ``"halt"`` (caller should break out of its loop). Returns ``False``
    otherwise — i.e. verification passed, OR failed but policy is
    ``"continue"``, OR the live capture errored out (skip with warning
    rather than fail), OR the stop flag was tripped mid-flight.

    ``on_fail`` is invoked exactly once on a comparison failure with
    the recorded event, the human-readable diff string, the expected
    image, and the live capture. Exceptions raised inside the callback
    are swallowed so a buggy UI handler can't take down playback.
    """
    # Resolve capture region. For Model B use the live target rect (which
    # may have moved/resized since recording). For Model A use the
    # recorded monitor rect.
    region: Optional[tuple] = None
    if target is not None:
        target.refresh()
        region = target.screenshot_region()
    elif recording.monitor:
        m = recording.monitor
        region = (int(m["x"]), int(m["y"]),
                  int(m["width"]), int(m["height"]))

    if stop_flag.is_set():
        return False
    try:
        live = take_stable_screenshot(
            region=region,
            poll_interval=config.STABLE_POLL_INTERVAL_SECONDS,
            max_wait=config.STABLE_MAX_WAIT_SECONDS,
            phash_distance=config.STABLE_PHASH_DISTANCE,
        )
    except Exception as exc:
        print(f"[verify] capture failed: {exc!r}; skipping")
        return False
    if stop_flag.is_set():
        return False

    try:
        expected = base64_to_image(
            recording.screenshots[event.before_screenshot]
        )
    except Exception as exc:
        print(f"[verify] failed to decode expected before-shot: {exc!r}; skipping")
        return False

    passed, _diff_value, diff_text = compare_screenshots(
        live, expected,
        method=config.VERIFY_METHOD,
        tolerance_pct=config.VERIFY_TOLERANCE_PCT,
        pixel_threshold=config.VERIFY_PIXEL_THRESHOLD,
        phash_max_distance=config.VERIFY_PHASH_MAX_DISTANCE,
    )
    # Always notify on_capture so the UI can cache the pre-action live
    # image alongside the expected before-shot, regardless of outcome.
    if on_capture is not None:
        try:
            on_capture(event, expected, live, diff_text, passed)
        except Exception:
            pass
    if passed:
        return False

    # Failure: invoke callback, then decide based on policy.
    if on_fail is not None:
        try:
            on_fail(event, diff_text, expected, live)
        except Exception:
            pass
    if config.VERIFY_ON_MISMATCH == "continue":
        print(f"[verify] step {event.step}: mismatch {diff_text} "
              f"({config.VERIFY_METHOD}) — continuing per config")
        return False
    # halt
    print(f"[verify] step {event.step}: mismatch {diff_text} "
          f"({config.VERIFY_METHOD}) — halting playback")
    return True


def should_verify(event: RecordedEvent, recording: Recording,
                  warmup_skipped_event_index: int, event_index: int) -> bool:
    """Whether the player should run verification for ``event``.

    Encapsulates the gating conditions that the player loop used to
    inline: master toggle, Model B warm-up event skip, and presence of a
    valid before-shot in the recording.
    """
    if not config.VERIFY_BEFORE_ACTION:
        return False
    if event_index == warmup_skipped_event_index:
        return False
    if not event.before_screenshot:
        return False
    if event.before_screenshot not in recording.screenshots:
        return False
    return True


def make_diff_image(
    expected: Image.Image,
    live: Image.Image,
    *,
    threshold: int = 16,
    base_brightness: float = 0.5,
) -> Image.Image:
    """Return an RGB image visualizing per-pixel differences.

    The returned image is the LIVE capture rendered as a darkened
    greyscale base, with pixels that differ from ``expected`` (per-channel
    max delta > ``threshold``) overlaid in pure red. This keeps the
    user's UI context recognizable while making changed regions pop.

    If ``live`` and ``expected`` differ in size, ``live`` is resized
    (NEAREST) to ``expected.size`` so the per-pixel comparison aligns.
    """
    a = expected.convert("RGB")
    b = live.convert("RGB")
    if b.size != a.size:
        b = b.resize(a.size, Image.Resampling.NEAREST)

    # Darkened greyscale rendering of the live capture as the base.
    grey = b.convert("L")
    darkened = grey.point(lambda v: int(v * base_brightness))
    base = Image.merge("RGB", (darkened, darkened, darkened))

    # Per-pixel "max channel delta" reduced to a single L band.
    diff = ImageChops.difference(a, b)
    max_band = diff.getchannel(0)
    for ch in (1, 2):
        max_band = ImageChops.lighter(max_band, diff.getchannel(ch))
    # Binary mask: 255 where the delta exceeds threshold, else 0.
    mask = max_band.point(lambda v: 255 if v > threshold else 0)

    red = Image.new("RGB", a.size, (255, 0, 0))
    base.paste(red, (0, 0), mask)
    return base
