"""Optional LoRA fine-tune of the base SLM on the query-parsing task (free Colab/Kaggle T4 is enough).
pip install -r training/requirements.txt
python training/make_nlu_data.py --n 3000
python training/train_lora.py --base Qwen/Qwen2.5-1.5B-Instruct --out ./geoai-slm-merged
Then: python scripts/publish_model.py --path ./geoai-slm-merged --repo <you>/geoai-outdoor-slm --fine-tuned
NOTE: written for transformers+peft APIs of 2025-26; not executed in the authoring sandbox (no GPU/network) - run a quick
smoke (--max-steps 20) first.
"""
import argparse
import json

import torch
from peft import LoraConfig, get_peft_model
from transformers import (AutoModelForCausalLM, AutoTokenizer, DataCollatorForSeq2Seq, Trainer, TrainingArguments)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--data", default="training/nlu_train.jsonl")
    ap.add_argument("--out", default="./geoai-slm-merged")
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--max-steps", type=int, default=-1)
    a = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(a.base)
    model = AutoModelForCausalLM.from_pretrained(a.base, torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32)
    model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, task_type="CAUSAL_LM",
                                             target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    model.print_trainable_parameters()

    def encode(row):
        user, target = row["messages"][0], row["messages"][1]["content"]
        prompt = tok.apply_chat_template([user], tokenize=False, add_generation_prompt=True)
        p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
        t_ids = tok(target + tok.eos_token, add_special_tokens=False)["input_ids"]
        return {"input_ids": p_ids + t_ids, "attention_mask": [1] * (len(p_ids) + len(t_ids)),
                "labels": [-100] * len(p_ids) + t_ids}          # loss only on the JSON answer

    rows = [encode(json.loads(l)) for l in open(a.data, encoding="utf-8")]
    args = TrainingArguments(output_dir="lora-out", per_device_train_batch_size=8, gradient_accumulation_steps=2, learning_rate=2e-4,
                             num_train_epochs=a.epochs, max_steps=a.max_steps, logging_steps=20, save_strategy="no", report_to=[],
                             bf16=torch.cuda.is_available(), remove_unused_columns=False)
    Trainer(model=model, args=args, train_dataset=rows, data_collator=DataCollatorForSeq2Seq(tok, padding=True)).train()
    merged = model.merge_and_unload()
    merged.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    print("saved merged model to", a.out)


if __name__ == "__main__":
    main()
