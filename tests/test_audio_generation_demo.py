"""Test audio generation with mocked TTS (no API key required)."""

from pathlib import Path
import json
from datetime import datetime
from unittest.mock import Mock, patch

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


def create_mock_audio_file(output_path: Path, text: str) -> int:
    """Create a valid playable silent MP3 file for testing."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Estimate duration based on text
    # ~150 words per minute, ~2.5 words per second
    words = len(text.split())
    estimated_seconds = words / 2.5
    
    # Create valid MP3 file structure that will play
    # ID3v2.3 header (10 bytes)
    id3_header = bytes([
        0x49, 0x44, 0x33,  # "ID3"
        0x03, 0x00,         # Version 2.3.0
        0x00,               # Flags
        0x00, 0x00, 0x00, 0x00  # Size (0)
    ])
    
    # MPEG-1 Layer 3 frame header for silence (32 kbps, 44100 Hz, mono)
    mpeg_frame = bytes([
        0xFF, 0xFB, 0x90, 0x00,  # Frame header
    ]) + bytes([0x00] * 152)  # Padding (156 bytes per frame)
    
    # Calculate frames needed (~26ms per frame at 44100 Hz)
    frames_needed = int(estimated_seconds / 0.026) + 1
    
    # Write valid MP3 file
    with open(output_path, 'wb') as f:
        f.write(id3_header)
        for _ in range(frames_needed):
            f.write(mpeg_frame)
    
    return output_path.stat().st_size


def main():
    """Generate audio for the test script (with mocked TTS)."""
    print("=" * 70)
    print("Audio Generation Test - Science Fiction Physics (DEMO MODE)")
    print("=" * 70)
    print("\n⚠️  Running in DEMO mode with mocked TTS (no API key required)")
    print("   In production, this would call ElevenLabs API\n")
    
    # Create output directory
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_dir = Path("results") / f"audio_test_demo_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"📁 Output directory: {output_dir}")
    
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
    
    print(f"\n🔊 Generating voiceover audio (mocked)...")
    
    try:
        # Mock the TTS generation function
        with patch('src.audio_agent.generate_voiceover') as mock_tts:
            def mock_generate_voiceover(text, voice_id, output_path, **kwargs):
                # Create mock audio file
                file_size = create_mock_audio_file(output_path, text)
                
                # Estimate duration
                words = len(text.split())
                estimated_duration = words / 2.5
                
                metadata = {
                    "voice_id": voice_id,
                    "character_count": len(text),
                    "file_size_bytes": file_size,
                    "estimated_duration_s": round(estimated_duration, 2),
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                }
                
                return output_path, metadata
            
            mock_tts.side_effect = mock_generate_voiceover
            
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
            print(f"   (Valid MP3 files with silence - real API adds actual voiceover)")
            
            # Display timeline details
            print(f"\n📋 Audio Timeline:")
            for track in audio_timeline['tracks']:
                if track['type'] == 'voiceover':
                    scene_id = track['scene_id']
                    t_start = track['t_start_s']
                    t_end = track['t_end_s']
                    duration = t_end - t_start
                    file_name = Path(track['file']).name
                    chars = track.get('metadata', {}).get('character_count', 0)
                    print(f"   [{scene_id}] {t_start:5.1f}s - {t_end:5.1f}s ({duration:4.1f}s) | {file_name} ({chars} chars)")
            
            # Show the actual audio timeline structure
            print(f"\n📄 Audio Timeline JSON Structure:")
            print(json.dumps(audio_timeline, indent=2)[:1000] + "...")
            
            print("\n" + "=" * 70)
            print("✨ Demo Test Complete!")
            print("=" * 70)
            print(f"\n📁 All files saved to: {output_dir}")
            print(f"\n💡 What happened:")
            print(f"   ✅ Video plan was validated")
            print(f"   ✅ Audio agent processed {len(video_plan['scenes'])} scenes")
            print(f"   ✅ Audio timeline manifest created with proper structure")
            print(f"   ✅ Mock MP3 files generated for each scene")
            print(f"   ✅ Statistics calculated")
            
            print(f"\n🎯 With a valid ElevenLabs API key:")
            print(f"   - Replace mock files with real AI-generated voiceover")
            print(f"   - Professional narrator voice (Rachel)")
            print(f"   - Natural speech with proper pacing and emphasis")
            print(f"   - Ready for video composition")
            
            return 0
        
    except Exception as e:
        print(f"\n❌ Error during audio generation:")
        print(f"   {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
