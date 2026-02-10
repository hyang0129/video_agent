"""Debug caption extraction from YouTube videos."""

from youtube_transcript_api import YouTubeTranscriptApi

def test_single_video():
    """Test caption extraction on a known-good video."""
    
    # Test with a popular Star Wars facts video
    test_videos = [
        {
            "id": "RySHDUU2juM",  # 101 Facts About Star Wars
            "title": "101 Facts About Star Wars"
        },
        {
            "id": "Z0PMq4XGtZ4",  # Star Wars Facts by Screen Rant
            "title": "Star Wars Facts"
        }
    ]
    
    for video in test_videos:
        video_id = video["id"]
        title = video["title"]
        
        print(f"\n{'='*60}")
        print(f"Testing video: {title}")
        print(f"Video ID: {video_id}")
        print(f"{'='*60}")
        
        try:
            # Create API instance and fetch transcript
            api = YouTubeTranscriptApi()
            transcript = api.fetch(video_id, ['en'])
            captions = " ".join([entry['text'] for entry in transcript])
            
            if captions:
                print(f"✓ Caption extraction successful!")
                print(f"  Caption length: {len(captions)} characters")
                print(f"  First 500 chars: {captions[:500]}")
                print(f"  Last 200 chars: {captions[-200:]}")
            else:
                print(f"✗ Caption extraction returned None")
                print(f"  Possible reasons:")
                print(f"    - Video has no captions")
                print(f"    - Captions are disabled")
                print(f"    - Video is private/deleted")
                
        except Exception as e:
            print(f"✗ Caption extraction failed with error:")
            print(f"  {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_single_video()
