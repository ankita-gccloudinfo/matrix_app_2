import os
import io
import torch
import numpy as np

nemotron_model = None
IS_CUDA_AVAILABLE = torch.cuda.is_available()
DEVICE = "cuda" if IS_CUDA_AVAILABLE else "cpu"

def load_nemotron_model():
    """
    Loads Nemotron-3.5-ASR-streaming-0.6b model onto CUDA (NVIDIA A10 GPU) or CPU.
    """
    global nemotron_model
    try:
        print(f"🎙️ Loading Nemotron-3.5-ASR-streaming-0.6b model on device: {DEVICE}...")
        
        # Try loading via NVIDIA NeMo ASR if installed
        try:
            import nemo.collections.asr as nemo_asr
            nemotron_model = nemo_asr.models.EncDecRNNTBPEModel.from_pretrained(
                model_name="nvidia/nemotron-3.5-asr-streaming-0.6b"
            ).to(DEVICE)
            nemotron_model.eval()
            print("🎙️ Nemotron 3.5 ASR loaded via NeMo!")
            return
        except ImportError:
            print("ℹ️ NeMo toolkit not installed, attempting HuggingFace transformers pipeline...")

        # Fallback to HuggingFace transformers pipeline / AutoModel if NeMo is not installed
        try:
            from transformers import pipeline
            nemotron_model = pipeline(
                "automatic-speech-recognition",
                model="nvidia/nemotron-3.5-asr-streaming-0.6b",
                device=0 if IS_CUDA_AVAILABLE else -1,
                torch_dtype=torch.float16 if IS_CUDA_AVAILABLE else torch.float32
            )
            print("🎙️ Nemotron 3.5 ASR loaded via Transformers!")
            return
        except Exception as hf_err:
            print(f"ℹ️ HuggingFace load notice: {hf_err}")

        print("⚠️ Nemotron ASR dependencies not present. Server will fallback to audio buffer processor.")
    except Exception as e:
        print(f"⚠️ Nemotron ASR model failed to load: {e}")

def get_nemotron_model():
    return nemotron_model

class NemotronAudioStreamSession:
    """
    Handles stateful audio streaming per WebSocket client connection.
    Accumulates 16kHz 16-bit mono PCM chunks and returns transcriptions.
    """
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self.audio_buffer = bytearray()
        self.total_samples = 0

    def append_audio_chunk(self, raw_bytes: bytes):
        """Appends raw PCM int16 or WAV bytes to session buffer."""
        self.audio_buffer.extend(raw_bytes)

    def process_buffer(self) -> str:
        """
        Processes accumulated PCM buffer and returns transcribed text.
        """
        if len(self.audio_buffer) < 3200:  # Need at least 0.1s of 16kHz audio
            return ""

        # Convert bytearray to float32 numpy array normalized to [-1.0, 1.0]
        pcm_data = np.frombuffer(self.audio_buffer, dtype=np.int16).astype(np.float32) / 32768.0
        
        model = get_nemotron_model()
        if model is None:
            # Fallback if model not loaded locally
            return ""

        try:
            if hasattr(model, 'transcribe'):
                # NeMo EncDecRNNTBPEModel transcribe
                transcriptions = model.transcribe([pcm_data])
                if isinstance(transcriptions, list) and len(transcriptions) > 0:
                    return transcriptions[0]
            elif callable(model):
                # Transformers pipeline
                res = model({"sampling_rate": self.sample_rate, "raw": pcm_data})
                return res.get("text", "")
        except Exception as e:
            print(f"Error processing Nemotron ASR buffer: {e}")
            return ""

        return ""

    def reset(self):
        self.audio_buffer.clear()
        self.total_samples = 0
