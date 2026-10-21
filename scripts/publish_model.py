"""Create the public Hugging Face repo required by the rules (weights + model card + open licence).

Case A - base model used unchanged:  python scripts/publish_model.py --base Qwen/Qwen2.5-1.5B-Instruct --repo <you>/geoai-outdoor-slm
Case B - your fine-tuned/merged dir:  python scripts/publish_model.py --path ./geoai-slm-merged --repo <you>/geoai-outdoor-slm --fine-tuned
Needs: huggingface-cli login (write token).  The repo then loads with AutoModelForCausalLM.from_pretrained("<you>/geoai-outdoor-slm").
"""
import argparse
from pathlib import Path

from huggingface_hub import HfApi
from transformers import AutoModelForCausalLM, AutoTokenizer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--path", help="local dir of fine-tuned/merged weights (omit to republish the base unchanged)")
    ap.add_argument("--fine-tuned", action="store_true")
    ap.add_argument("--private", action="store_true", help="NOT for submission: rules require a public repo")
    a = ap.parse_args()

    src = a.path or a.base
    tok, model = AutoTokenizer.from_pretrained(src), AutoModelForCausalLM.from_pretrained(src)
    n = sum(p.numel() for p in model.parameters())
    assert n <= 3_000_000_000, f"{n/1e9:.2f}B parameters exceeds the 3B cap"
    print(f"{n/1e9:.2f}B parameters OK")

    card = (Path(__file__).resolve().parent.parent / "hf_model" / "README.md").read_text(encoding="utf-8")
    card = (card.replace("{{BASE}}", a.base).replace("{{PARAMS}}", f"{n/1e9:.2f}B")
                .replace("{{CHANGES}}", "LoRA fine-tuned (merged) on synthetic query-parsing data; see training/ in the code repo." if a.fine_tuned
                         else "None. The base weights are used unchanged; behaviour is controlled by prompts and the verification layer in the code repo."))
    api = HfApi()
    api.create_repo(a.repo, exist_ok=True, private=a.private)
    model.push_to_hub(a.repo, private=a.private)
    tok.push_to_hub(a.repo, private=a.private)
    api.upload_file(path_or_fileobj=card.encode(), path_in_repo="README.md", repo_id=a.repo)
    print("published: https://huggingface.co/" + a.repo)


if __name__ == "__main__":
    main()
