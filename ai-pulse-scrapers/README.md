# AI Pulse — scrapers (Phase 1)

Phase 1 data pipeline for AI Pulse. Standalone scrapers + LLM integration.

## Setup

```bash
python -m venv .venv
```

Activate the virtual environment (Windows PowerShell: `.\.venv\Scripts\Activate.ps1`), then:

```bash
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` with your API keys.

## Usage

```bash
python run_scrapers.py
python run_pipeline.py
```
