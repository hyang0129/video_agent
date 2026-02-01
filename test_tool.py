from src.tools.youtube_tools import fetch_videos_corpus
import json

try:
    print("Testing fetch_videos_corpus...")
    # Use invoke with a dict for LangChain tools
    result = fetch_videos_corpus.invoke({"query": "science fiction", "max_results": 5})
    print("Success!")
    data = json.loads(result)
    print(f"Found {len(data['videos'])} videos.")
except Exception as e:
    print(f"Error: {e}")
