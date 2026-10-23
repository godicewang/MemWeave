# DeepSeek V4.1 text tokenizer

Source: https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/static/tokenizers/v41/tokenizer.json

SHA-256: `81f64d1248a68ce3663e07ab3ee48b851e5df0e32d27cb98e4c9a268151e8d99`

Upstream comparison revision: `deepseek-ai/DeepSeek-V4-Flash-Vision-Exp`, `6821d6ad3681a4b137b066b76094fa82ebd0a380`. MIT notices are preserved in LICENSE.upstream (original data) and LICENSE.deepseek (recipe repository). Image-token reassignment is upstream's change; MemWeave stores the file unchanged and disables added-token matching in memory so user-written control spellings remain ordinary text. Image cost is reserved separately. No network download or Python runtime is needed by users.

Text tokens are counted with @huggingface/tokenizers 0.2.0. Provider framing is conservatively budgeted separately; this is not a claim to reproduce all hidden provider formatting. Unknown model revisions/providers use an explicitly labeled conservative estimator.
