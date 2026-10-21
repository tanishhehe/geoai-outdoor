"""Small language model wrapper (<= 3B parameters, open weights, runs locally in this process).

backend=transformers : AutoModelForCausalLM.from_pretrained(<your HF repo>)   (the submission path)
backend=llama_cpp    : same model as a GGUF quantisation, ~4x faster on CPU
backend=none         : no model (unit tests only; the API reports narrative_source = template)
"""
import threading

from .config import get_settings


class NullSLM:
    available = False
    model_id = "none"

    def generate(self, messages, max_new_tokens=None):
        raise RuntimeError("no SLM configured")


class SLM:
    available = True

    def __init__(self):
        s = get_settings()
        self.s = s
        self.model_id = s.slm_model_id
        self.backend = s.slm_backend
        self._lock = threading.Lock()
        self._model = self._tok = None
        self.loaded = False

    def load(self):
        with self._lock:
            if self.loaded:
                return
            s = self.s
            if self.backend == "llama_cpp":
                from llama_cpp import Llama
                self._model = Llama.from_pretrained(repo_id=self.model_id, filename=s.slm_gguf_file, n_ctx=4096,
                                                    n_threads=s.slm_threads, verbose=False)
            else:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer
                torch.set_num_threads(s.slm_threads)
                self._tok = AutoTokenizer.from_pretrained(self.model_id)
                self._model = AutoModelForCausalLM.from_pretrained(self.model_id, torch_dtype=getattr(torch, s.slm_dtype))
                self._model.eval()
            self.loaded = True

    def generate(self, messages, max_new_tokens=None) -> str:
        self.load()
        n = max_new_tokens or self.s.slm_max_new_tokens
        with self._lock:      # one generation at a time: tiny CPU box, predictable latency
            if self.backend == "llama_cpp":
                r = self._model.create_chat_completion(messages=messages, max_tokens=n, temperature=0.0)
                return r["choices"][0]["message"]["content"].strip()
            import torch
            text = self._tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inp = self._tok(text, return_tensors="pt")
            with torch.inference_mode():
                out = self._model.generate(**inp, max_new_tokens=n, do_sample=False, repetition_penalty=1.05)
            return self._tok.decode(out[0][inp["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def make_slm():
    return NullSLM() if get_settings().slm_backend == "none" else SLM()
