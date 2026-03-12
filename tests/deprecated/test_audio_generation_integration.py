"""Test audio generation with a real script."""

from pathlib import Path
import json
from datetime import datetime

from src.audio_agent import create_audio_agent


# Create a video plan with actual voiceover content
video_plan = {
    "schema_version": "1.0.0",
    "created_at": datetime.now().isoformat(),
    "video_plan_id": "vp_test_audio_trial",
    "topic_id": "science_fiction_facts",
    "subtopic_id": "sci_fi_physics",
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
            "t_end_s": 8.0,
            "vo_line": "Did you know some of the wildest sci-fi concepts aren't just fantasy? They're based on real, mind-bending physics!",
            "on_screen_text": "Sci-Fi Physics"
        },
        {
            "scene_id": "scene_02",
            "t_start_s": 8.0,
            "t_end_s": 18.0,
            "vo_line": "First, time travel. Einstein proved time dilation is real. The closer you are to massive gravity, like a black hole, the slower time moves for you.",
            "on_screen_text": "Time Dilation"
        },
        {
            "scene_id": "scene_03",
            "t_start_s": 18.0,
            "t_end_s": 28.0,
            "vo_line": "Next, wormholes. These cosmic shortcuts are mathematically possible! They're theoretical tunnels that fold space-time, connecting distant points instantly.",
            "on_screen_text": "Wormholes"
        },
        {
            "scene_id": "scene_04",
            "t_start_s": 28.0,
            "t_end_s": 38.0,
            "vo_line": "Finally, the multiverse. Some quantum theories suggest infinite parallel universes exist. Every choice you didn't make is happening in a reality right next to ours.",
            "on_screen_text": "The Multiverse"
        },
        {
            "scene_id": "scene_05",
            "t_start_s": 38.0,
            "t_end_s": 45.0,
            "vo_line": "Pretty wild, right? Which science fiction concept do you wish was real?",
            "on_screen_text": "What's Your Pick?"
        }
    ]
}


def main():
    """Generate audio for the test script."""
    print("=" * 70)
    print("Audio Generation Test - Science Fiction Physics")
    print("=" * 70)
    
    # Create output directory
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_dir = Path("results") / f"audio_test_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n📁 Output directory: {output_dir}")
    
    # Save video plan for reference
    video_plan_path = output_dir / "video_plan_input.json"
    with open(video_plan_path, "w", encoding="utf-8") as f:
        json.dump(video_plan, f, indent=2, ensure_ascii=False)
    print(f"   Saved: video_plan_input.json")
    
    # Create audio agent
    print(f"\n🎙️  Creating audio agent...")
    print(f"   Voice: narrator (Rachel - clear, professional)")
    print(f"   Music volume: -18.0 dB")
    
    audio_agent = create_audio_agent(
        output_dir=output_dir,
        voice="narrator",
        music_volume_db=-18.0
    )
    
    # Display script summary
    print(f"\n📋 Script Summary:")
    print(f"   Scenes: {len(video_plan['scenes'])}")
    print(f"   Total duration: {video_plan['scenes'][-1]['t_end_s']}s")
    
    total_chars = sum(len(s['vo_line']) for s in video_plan['scenes'])
    print(f"   Total characters: {total_chars}")
    
    print(f"\n🔊 Generating voiceover audio...")
    print(f"   This will call ElevenLabs API for each scene...")
    print(f"   Please wait...\n")
    
    try:
        # Generate audio timeline
        audio_timeline = audio_agent.generate_audio_timeline(video_plan)
        
        print("\n✅ Audio generation complete!")
        print(f"   Timeline ID: {audio_timeline['audio_timeline_id']}")
        print(f"   Duration: {audio_timeline['duration_seconds']}s")
        
        # Get and display statistics
        stats = audio_agent.get_audio_stats(audio_timeline)
        print(f"\n📊 Audio Statistics:")
        print(f"   Voiceover tracks: {stats['voiceover_tracks']}")
        print(f"   Music tracks: {stats['music_tracks']}")
        print(f"   Total characters: {stats['total_characters']}")
        print(f"   Avg chars/second: {stats['avg_chars_per_second']}")
        
        # Display generated files
        print(f"\n📄 Generated Files:")
        timeline_path = output_dir / "audio_timeline.json"
        timeline_size = timeline_path.stat().st_size / 1024
        print(f"   ✓ audio_timeline.json ({timeline_size:.1f} KB)")
        
        segments_dir = output_dir / "audio_segments"
        total_audio_size = 0
        if segments_dir.exists():
            audio_files = sorted(segments_dir.glob("*.mp3"))
            for audio_file in audio_files:
                size_kb = audio_file.stat().st_size / 1024
                total_audio_size += size_kb
                print(f"   ✓ {audio_file.name} ({size_kb:.1f} KB)")
        
        print(f"\n   Total audio size: {total_audio_size:.1f} KB")
        
        # Display timeline details
        print(f"\n📋 Audio Timeline:")
        for track in audio_timeline['tracks']:
            if track['type'] == 'voiceover':
                scene_id = track['scene_id']
                t_start = track['t_start_s']
                t_end = track['t_end_s']
                duration = t_end - t_start
                file_name = Path(track['file']).name
                print(f"   [{scene_id}] {t_start:5.1f}s - {t_end:5.1f}s ({duration:4.1f}s) | {file_name}")
        
        print("\n" + "=" * 70)
        print("✨ Test Complete!")
        print("=" * 70)
        print(f"\n📁 All files saved to: {output_dir}")
        print(f"\n💡 Next steps:")
        print(f"   1. Listen to the generated MP3 files in audio_segments/")
        print(f"   2. Review audio_timeline.json for timing details")
        print(f"   3. Phase 2: Mix with background music and export master file")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error during audio generation:")
        print(f"   {type(e).__name__}: {e}")
        print(f"\n💡 Troubleshooting:")
        print(f"   - Check ELEVENLABS_API_KEY is set in .env")
        print(f"   - Verify API key is valid and has quota remaining")
        print(f"   - Check network connectivity")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
