.PHONY: demo test serve

demo:
	uv run python -m backend.pipeline demo

test:
	uv run python -m unittest discover -s backend/tests

serve:
	uv run python -m http.server 8765
