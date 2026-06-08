"""LoRA fine-tune the base model on the oracle-verified dataset (Sovereign Brain
v2, M-D). Heavy GPU imports (torch/transformers/trl/peft) live inside main() so
the pure formatter is importable and testable without a GPU.

Run on the H200s:
  python -m scripts.train_lora --train data/sovereign-brain/train.jsonl \
      --out /raid/team/adapters/sovereign-brain
"""

import argparse
import json


def format_chat_example(record: dict) -> dict:
    """One JSONL row -> a chat example for SFTTrainer. The assistant turn is the
    strict decision JSON, so train-time output matches the served _DECISION_SCHEMA."""
    return {"messages": [
        {"role": "system", "content": record["system"]},
        {"role": "user", "content": record["user"]},
        {"role": "assistant",
         "content": json.dumps(record["assistant"], ensure_ascii=False)},
    ]}


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--train", required=True, help="train.jsonl from gen_dataset")
    p.add_argument("--out", default="/raid/team/adapters/sovereign-brain")
    p.add_argument("--base-model", dest="base_model",
                   default="nvidia/Llama-3.1-Nemotron-Nano-8B-v1")
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--batch", type=int, default=4)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--lora-r", dest="lora_r", type=int, default=16)
    p.add_argument("--lora-alpha", dest="lora_alpha", type=int, default=32)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args(argv)


def _load_examples(path):
    with open(path, "r", encoding="utf-8") as f:
        return [format_chat_example(json.loads(line)) for line in f if line.strip()]


def main():
    args = parse_args()

    import torch
    from datasets import Dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig
    from trl import SFTTrainer, SFTConfig

    ds = Dataset.from_list(_load_examples(args.train))
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model, torch_dtype=torch.bfloat16, device_map="auto")

    peft_config = LoraConfig(
        r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0.05,
        task_type="CAUSAL_LM", target_modules="all-linear")
    sft_config = SFTConfig(
        output_dir=args.out, num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch, learning_rate=args.lr,
        bf16=True, logging_steps=10, save_strategy="epoch", seed=args.seed)

    trainer = SFTTrainer(
        model=model, args=sft_config, train_dataset=ds,
        peft_config=peft_config, processing_class=tokenizer)
    trainer.train()
    trainer.save_model(args.out)
    print(f"adapter saved to {args.out}")


if __name__ == "__main__":
    main()
