"""Phone sound effects — short wav cues via pygame.mixer (thread-safe, separate from BGM).

pygame.mixer.Sound plays on auto-allocated channels, independent of the main app's
BGM (pygame.mixer.music) and TTS, so these UI cues never interrupt them. Every call
is wrapped so a missing file / uninitialised mixer never raises into the UI.
"""

from __future__ import annotations

from pathlib import Path

_SND_DIR = Path(__file__).parent / "assets" / "sounds"
_VOLUME = 0.7

# named cues → wav files
SMS_SEND = "sms_send.wav"
RINGTONE = "ringtone.wav"    # incoming call ring (loop while ringing)
DIAL = "dial.wav"            # outgoing call — dialing cue (one-shot)
BUSY = "busy.wav"            # outgoing call — ring-back tone while awaiting answer (loop)
HANGUP = "hangup.wav"        # any hang-up (player→char or char→player)
SHUTTER = "shutter.wav"      # camera shutter

_cache: dict = {}       # filename -> pygame Sound
_channels: dict = {}    # key -> pygame Channel (looping cues we can stop)


def _sound(filename: str):
    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        snd = _cache.get(filename)
        if snd is None:
            p = _SND_DIR / filename
            if not p.is_file():
                return None
            snd = pygame.mixer.Sound(str(p))
            snd.set_volume(_VOLUME)
            _cache[filename] = snd
        return snd
    except Exception:
        return None


def play(filename: str, *, loop: bool = False, key: str | None = None) -> None:
    """Play a cue once, or looping if loop=True (kept under `key` so stop(key) ends it)."""
    snd = _sound(filename)
    if snd is None:
        return
    try:
        chan = snd.play(loops=-1 if loop else 0)
        if key:
            _channels[key] = chan
    except Exception:
        pass


def stop(key: str) -> None:
    """Stop a looping cue started with the given key (no-op if not playing)."""
    chan = _channels.pop(key, None)
    if chan is not None:
        try:
            chan.stop()
        except Exception:
            pass
