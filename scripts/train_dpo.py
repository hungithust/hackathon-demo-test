"""DPO fine-tune on the oracle preference pairs (Sovereign Brain v2, M-E stretch).
Initializes from the M-D SFT adapter and prefers the oracle's best action over the
worst. Heavy GPU imports live inside main() so the pure formatter is testable.

Run on the H200s:
  python -m scripts.train_dpo --prefs data/sovereign-brain/prefs.jsonl \
      --adapter /raid/team/adapters/sovereign-brain \
      --out /raid/team/adapters/sovereign-brain-dpo
"""

import argparse
import json


def format_dpo_example(record: dict) -> dict:
    """One prefs.jsonl row -> a conversational DPO example (prompt/chosen/rejected).
    chosen/rejected assistant turns are the strict decision JSON."""
    return {
        "prompt": [{"role": "system", "content": record["system"]},
                   {"role": "user", "content": record["user"]}],
        "chosen": [{"role": "assistant",
                    "content": json.dumps(record["chosen"], ensure_ascii=False)}],
        "rejected": [{"role": "assistant",
                      "content": json.dumps(record["rejected"], ensure_ascii=False)}],
    }


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--prefs", required=True, help="prefs.jsonl from gen_dataset --dpo")
    p.add_argument("--adapter", default="/raid/team/adapters/sovereign-brain",
                   help="SFT adapter (M-D) to initialize from")
    p.add_argument("--out", default="/raid/team/adapters/sovereign-brain-dpo")
    p.add_argument("--base-model", dest="base_model",
                   default="nvidia/Llama-3.1-Nemotron-Nano-8B-v1")
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--beta", type=float, default=0.1)
    p.add_argument("--lr", type=float, default=5e-6)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args(argv)


def _load_prefs(path):
    with open(path, "r", encoding="utf-8") as f:
        return [format_dpo_example(json.loads(line)) for line in f if line.strip()]


def main():
    args = parse_args()

    import torch
    from datasets import Dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    from trl import DPOConfig, DPOTrainer

    ds = Dataset.from_list(_load_prefs(args.prefs))
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    base = AutoModelForCausalLM.from_pretrained(
        args.base_model, torch_dtype=torch.bfloat16, device_map="auto")
    model = PeftModel.from_pretrained(base, args.adapter, is_trainable=True)

    dpo_config = DPOConfig(
        output_dir=args.out, num_train_epochs=args.epochs, beta=args.beta,
        learning_rate=args.lr, bf16=True, logging_steps=10,
        save_strategy="epoch", seed=args.seed)
    trainer = DPOTrainer(
        model=model, args=dpo_config, train_dataset=ds, processing_class=tokenizer)
    trainer.train()
    trainer.save_model(args.out)
    print(f"DPO adapter saved to {args.out}")


if __name__ == "__main__":
    main()
