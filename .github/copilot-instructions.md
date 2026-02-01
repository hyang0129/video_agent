# Short Form Video Agent - Project Instructions

## Project Overview
Short Form Video Agent is an AI-powered pipeline that identifies market opportunities on YouTube and generates short-form video content.

## Tech Stack
- **Language**: Python 3.10+
- **Framework**: LangChain (v0.1.20)
- **AI Models**: Google Gemini (via `langchain-google-genai`)
- **APIs**: YouTube Data API v3

## Development Guidelines

### Code Style
- **Type Hints**: Mandatory for all function arguments and return values.
- **Docstrings**: Google Style docstrings for all modules, classes, and functions.
- **Formatting**: Follow PEP 8.

### Key Components
- **`src/agent.py`**: Contains the `MarketResearchAgent` class and prompts.
  - configured to use `gemini-flash-latest`.
  - Uses `AgentExecutor` with `fetch_videos_corpus` and `compare_content_gap` tools.
- **`src/tools/youtube_tools.py`**: Handles all YouTube API interactions.
  - Implements caching and quota management.
  - Provides tools: `search_longform_content`, `fetch_videos_corpus`, `compare_content_gap`.

### Testing & Execution
- Run example research: `python main.py example1`
- Run interactive mode: `python main.py interactive`
- Suppress warnings: `main.py` includes `warnings.filterwarnings` to handle Google API deprecation notices.

### Dependency Management
- Context is sensitive to `langchain` versions.
- Pinned versions in `requirements.txt`:
  - `langchain==0.1.20`
  - `langchain-google-genai==1.0.3`
