"""Example usage of the Audio Generation Agent.

This script demonstrates how to use the AudioGenerationAgent to convert
a VideoPlan into an AudioTimeline with voiceover generation.

Prerequisites:
    - ELEVENLABS_API_KEY must be set in .env file
    - VideoPlan JSON (from video_agent.py output)

Usage:
    python examples/audio_agent_example.py
"""

from pathlib import Path
import json
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.audio_agent import create_audio_agent
from src.config import RESULTS_DIR


# Example VideoPlan (minimal structure)
EXAMPLE_VIDEO_PLAN = {
    "schema_version": "1.0.0",
    "created_at": "2026-02-01T12:00:00Z",
    "video_plan_id": "vp_example_123",
    "topic_id": "science_fiction",
    "subtopic_id": "time_dilation",
    "audio": {
        "tts": {
            "enabled": True,
            "voice": "narrator"
        }
    },
    "scenes": [
        {
            "scene_id": "scene_01",
            "t_start_s": 0.0,
            "t_end_s": 6.5,
            "vo_line": "Have you ever wondered why time moves slower near massive objects?",
            "on_screen_text": "Time Dilation",
        },
        {
            "scene_id": "scene_02",
            "t_start_s": 6.5,
            "t_end_s": 13.0,
            "vo_line": "Einstein's theory of relativity explains this fascinating phenomenon.",
            "on_screen_text": "Einstein's Theory",
        },
        {
            "scene_id": "scene_03",
            "t_start_s": 13.0,
            "t_end_s": 20.0,
            "vo_line": "Near a black hole, time can slow down by incredible amounts.",
            "on_screen_text": "Black Holes",
        },
    ]
}


def main():
    """Run audio generation example."""
    print("=" * 60)
    print("Audio Generation Agent - Example")
    print("=" * 60)
    
    # Create output directory for this example
    output_dir = RESULTS_DIR / "audio_example"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n📁 Output directory: {output_dir}")
    
    # Create audio agent with custom voice
    print("\n🎙️  Creating audio agent...")
    audio_agent = create_audio_agent(
        output_dir=output_dir,
        voice="narrator",  # Can also use: "energetic", "calm", "authoritative"
        music_volume_db=-18.0,
    )
    
    # Generate audio timeline
    print("\n🔊 Generating audio timeline...")
    print("This will call ElevenLabs API for TTS generation...")
    
    try:
        audio_timeline = audio_agent.generate_audio_timeline(EXAMPLE_VIDEO_PLAN)
        
        print("\n✅ Audio timeline generated successfully!")
        print(f"   Timeline ID: {audio_timeline['audio_timeline_id']}")
        print(f"   Duration: {audio_timeline['duration_seconds']}s")
        print(f"   Tracks: {len(audio_timeline['tracks'])}")
        
        # Get statistics
        stats = audio_agent.get_audio_stats(audio_timeline)
        print("\n📊 Audio Statistics:")
        print(f"   Voiceover tracks: {stats['voiceover_tracks']}")
        print(f"   Music tracks: {stats['music_tracks']}")
        print(f"   Total characters: {stats['total_characters']}")
        print(f"   Avg chars/second: {stats['avg_chars_per_second']}")
        
        # Show generated files
        print("\n📄 Generated Files:")
        timeline_path = output_dir / "audio_timeline.json"
        print(f"   {timeline_path}")
        
        segments_dir = output_dir / "audio_segments"
        if segments_dir.exists():
            for segment_file in sorted(segments_dir.glob("*.mp3")):
                size_kb = segment_file.stat().st_size / 1024
                print(f"   {segment_file} ({size_kb:.1f} KB)")
        
        # Display timeline structure
        print("\n📋 Audio Timeline Structure:")
        for track in audio_timeline['tracks']:
            track_type = track['type']
            track_file = track['file']
            t_start = track['t_start_s']
            t_end = track['t_end_s']
            print(f"   [{track_type:10s}] {t_start:5.1f}s - {t_end:5.1f}s | {track_file}")
        
        print("\n" + "=" * 60)
        print("✨ Example completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nMake sure ELEVENLABS_API_KEY is set in your .env file")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
