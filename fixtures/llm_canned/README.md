# llm_canned

This directory is reserved for canned MockLLM responses if future tests need exact prompt-hash fixtures.

The current offline implementation keeps MockLLM deterministic in code, so no canned JSON files are required for `uv run python -m backend.pipeline demo`.

