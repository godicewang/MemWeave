# Local Task embedding resources

Only this manifest and attribution ship in the package. Weights are downloaded on
first Task search from the pinned public conversion, verified by file size and
SHA-256, then stored outside the repository under `~/.pi/memory/models/`.

- Original: [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small)
  (model card declares MIT; multilingual E5, 384 dimensions, 512-token input).
- Q8 ONNX conversion: [Xenova/multilingual-e5-small](https://huggingface.co/Xenova/multilingual-e5-small/tree/761b726dd34fb83930e26aab4e9ac3899aa1fa78).
- Exact resource revision and SHA-256 checksums: `e5-small.json`.
- Inference: [ONNX Runtime Node](https://onnxruntime.ai/docs/get-started/with-javascript/node.html)
  1.30.0, CPU; tokenizer: existing `@huggingface/tokenizers` 0.2.0.
- Lexical search: [MiniSearch](https://github.com/lucaong/minisearch) 7.2.0.

The original E5 query/passage convention is implemented with `query: ` and
`passage: ` prefixes, mean pooling and L2 normalization. Search indexes Goal and
Task discovery fields only. No private text is sent to the model download host,
and no remote embedding API or remote model code is executed.

Model resources are about 135.4 MB in decimal units (129.1 MiB). Native runtime
installation and active process memory are additional; model size is not an RSS
bound. The row cache is separately bounded to 32 MiB by default. Download failure
or invalid checksums are errors, not silent lexical-only success. Model/derived
search files can be rebuilt; State and registered Pi Sessions cannot be replaced
by this cache.
