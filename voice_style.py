"""Per-reply delivery hints from fresh, validated local camera cues."""
from __future__ import annotations

from array import array
from dataclasses import dataclass
import math
import sys
from time import monotonic


@dataclass(frozen=True)
class VoiceStyle:
    name: str
    delivery: str
    gain: float = 1.0


STYLES = {
    "balanced": VoiceStyle("balanced", "Use a warm, natural conversational voice at a comfortable pace and normal volume."),
    "playful": VoiceStyle("playful", "Sound playful, fun, and warmly upbeat, with a smile in your voice, lively intonation, "
                         "and a light conversational bounce. Keep it natural, not exaggerated or loud. "
                         "Use gentle humor only when it fits the user's request."),
    "soothing": VoiceStyle("soothing", "Sound calm, soothing, and gentle. Use a slightly slower, unhurried pace, "
                          "softened intonation, relaxed pauses, and a quieter voice that remains clearly audible. "
                          "Keep the reply short and easy to follow; do not whisper or become breathy.", gain=.78),
    "supportive": VoiceStyle("supportive", "Sound patient, steady, and reassuring. Explain one clear step at a time, "
                             "with an even pace and no teasing, forced cheerfulness, or condescension."),
}


def style_for_camera(latest, *, now=None):
    """Use current stable cues, never retained episodes or inferred emotions."""
    now = monotonic() if now is None else now
    if not latest or latest.get("usable") is not True:
        return STYLES["balanced"]
    received = latest.get("received_at")
    if (not isinstance(received, (int, float)) or not math.isfinite(received)
            or not 0 <= now - received < 2):
        return STYLES["balanced"]
    cues = set(latest.get("cues", ()))
    if "neutral" in cues:
        return STYLES["balanced"]
    if cues.intersection({"tired_look", "sleepy_look"}):
        return STYLES["soothing"]
    if cues.intersection({"frowning", "furrowed_brow", "tense_expression", "confused_look", "irritated_look"}):
        return STYLES["supportive"]
    if "smiling" in cues:
        return STYLES["playful"]
    return STYLES["balanced"]


def delivery_instructions(style):
    return ("\n\nVOICE DELIVERY FOR THIS REPLY:\n" + style.delivery
            + "\nThis is a tentative delivery hint from visible cues, not evidence of the user's feelings or alertness. "
            "Do not mention the cue, label the user's emotions, or announce the style change. "
            "The user's explicit tone preferences and the seriousness of their request take precedence. "
            "Change delivery only; preserve the answer, task scope, and all action/confirmation rules. "
            "A delivery hint never requests speech or authorizes tools or actions.")


def soften_pcm16(data, gain):
    """Attenuate little-endian PCM16 without changing duration or sample count."""
    if gain == 1.0 or not data:
        return data
    if not math.isfinite(gain) or not 0 <= gain <= 1:
        raise ValueError("Playback gain must be between zero and one.")
    if len(data) % 2:
        raise ValueError("Realtime output is not aligned to 16-bit PCM samples.")
    samples = array("h")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    output = array("h", (round(sample * gain) for sample in samples))
    if sys.byteorder != "little":
        output.byteswap()
    return output.tobytes()
