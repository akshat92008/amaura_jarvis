"""
Unsloth Fine-Tuning Script for jarvis-fable5-32b.
Runs on Google Cloud Platform (GCP) Compute Engine GPU VM (NVIDIA L4 / A100 GPU)
funded by $300 GCP Credits.
Fine-tunes Qwen 2.5 Coder 32B using QLoRA into a custom Fable-5 model.
"""

import os
from pathlib import Path

TRAIN_SCRIPT = """# PyTorch Unsloth Fine-Tuning Pipeline for jarvis-fable5-32b
# Run on GCP Compute Engine GPU Instance (NVIDIA L4 24GB or A100 40GB)

from unsloth import FastLanguageModel
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments

max_seq_length = 4096
dtype = None # Auto detection
load_in_4bit = True # 4-bit QLoRA for fast memory efficiency

print("🚀 Loading Qwen 2.5 Coder 32B Base Model...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "Qwen/Qwen2.5-Coder-32B-Instruct",
    max_seq_length = max_seq_length,
    dtype = dtype,
    load_in_4bit = load_in_4bit,
)

model = FastLanguageModel.get_peft_model(
    model,
    r = 16,
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_alpha = 16,
    lora_dropout = 0,
    bias = "none",
    use_gradient_checkpointing = "unsloth",
)

# Load synthetic dataset
dataset = load_dataset("json", data_files="dataset_fable5.jsonl", split="train")

trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length = max_seq_length,
    dataset_num_proc = 2,
    packing = False,
    args = TrainingArguments(
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4,
        warmup_steps = 5,
        max_steps = 60,
        learning_rate = 2e-4,
        fp16 = True,
        logging_steps = 1,
        output_dir = "outputs",
    ),
)

print("⚡ Starting Unsloth Fine-Tuning Training Cycle...")
trainer.train()

print("💾 Saving fine-tuned model weights to ./jarvis-fable5-32b...")
model.save_pretrained_merged("jarvis-fable5-32b", tokenizer, save_method="merged_16bit")
print("✅ Training complete! Custom model jarvis-fable5-32b is ready for vLLM deployment.")
"""

if __name__ == "__main__":
    out_path = Path(__file__).parent.resolve() / "train_unsloth.py"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(TRAIN_SCRIPT)
    print(f"[Fine-Tune Setup] Created training script -> {out_path}")
