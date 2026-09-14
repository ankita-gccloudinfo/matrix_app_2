import os
from faster_whisper import WhisperModel

whisper_model = None

def load_whisper_model():
    global whisper_model
    try:
        print("🎙️ Loading Whisper model...")
        whisper_model = WhisperModel(
            "base",
            device="cpu",
            compute_type="int8",
            cpu_threads=1
        )
        print("🎙️ Whisper model loaded!")
    except Exception as e:
        print(f"⚠️ Whisper model failed to load: {e}")

def get_whisper_model():
    return whisper_model
