"""Tests for Audio Generation Agent.

Run with: pytest tests/test_audio_agent.py -v
"""

import pytest
from pathlib import Path
import json
from unittest.mock import Mock, patch, MagicMock

from video_agent.audio_agent import (
    AudioGenerationAgent,
    create_audio_agent,
    AudioGenerationError,
)
from video_agent.tools.tts_tools import TTSError


@pytest.fixture
def sample_video_plan():
    """Create a sample video plan for testing."""
    return {
        "schema_version": "1.0.0",
        "created_at": "2026-02-01T12:00:00Z",
        "video_plan_id": "vp_test_123",
        "topic_id": "test_topic",
        "subtopic_id": "test_subtopic",
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
                "t_end_s": 5.0,
                "vo_line": "This is test line one.",
                "on_screen_text": "Test 1",
            },
            {
                "scene_id": "scene_02",
                "t_start_s": 5.0,
                "t_end_s": 10.0,
                "vo_line": "This is test line two.",
                "on_screen_text": "Test 2",
            },
        ]
    }


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create temporary output directory."""
    output_dir = tmp_path / "audio_output"
    output_dir.mkdir()
    return output_dir


class TestAudioGenerationAgent:
    """Test AudioGenerationAgent class."""
    
    def test_init(self, temp_output_dir):
        """Test agent initialization."""
        agent = AudioGenerationAgent(
            output_dir=temp_output_dir,
            voice_id="narrator",
            music_volume_db=-18.0
        )

        assert agent.output_dir == temp_output_dir
        assert agent.voice_id == "JBFqnCBsd6RMkjVDRZzb"  # narrator preset
        assert agent.music_volume_db == -18.0
        assert agent.audio_segments_dir.exists()
    
    def test_validate_video_plan_valid(self, sample_video_plan, temp_output_dir):
        """Test validation with valid video plan."""
        agent = AudioGenerationAgent(output_dir=temp_output_dir)
        # Should not raise
        agent._validate_video_plan(sample_video_plan)
    
    def test_validate_video_plan_not_dict(self, temp_output_dir):
        """Test validation rejects non-dict input."""
        agent = AudioGenerationAgent(output_dir=temp_output_dir)
        
        with pytest.raises(AudioGenerationError, match="must be a dictionary"):
            agent._validate_video_plan("not a dict")
    
    def test_validate_video_plan_missing_scenes(self, temp_output_dir):
        """Test validation rejects plan without scenes."""
        agent = AudioGenerationAgent(output_dir=temp_output_dir)
        
        with pytest.raises(AudioGenerationError, match="missing 'scenes'"):
            agent._validate_video_plan({})
    
    def test_validate_video_plan_scenes_not_list(self, temp_output_dir):
        """Test validation rejects non-list scenes."""
        agent = AudioGenerationAgent(output_dir=temp_output_dir)
        
        with pytest.raises(AudioGenerationError, match="must be a list"):
            agent._validate_video_plan({"scenes": "not a list"})
    
    def test_validate_video_plan_missing_required_fields(self, temp_output_dir):
        """Test validation rejects scenes missing required fields."""
        agent = AudioGenerationAgent(output_dir=temp_output_dir)
        
        invalid_plan = {
            "scenes": [
                {"t_start_s": 0.0}  # Missing t_end_s and vo_line
            ]
        }
        
        with pytest.raises(AudioGenerationError, match="missing required field"):
            agent._validate_video_plan(invalid_plan)
    
    @patch('video_agent.audio_agent.generate_voiceover')
    def test_generate_audio_timeline(
        self,
        mock_generate_voiceover,
        sample_video_plan,
        temp_output_dir
    ):
        """Test audio timeline generation."""
        # Mock TTS generation
        mock_generate_voiceover.return_value = (
            temp_output_dir / "audio_segments" / "vo_scene_01.mp3",
            {
                "voice_id": "21m00Tcm4TlvDq8ikWAM",
                "character_count": 23,
                "file_size_bytes": 50000,
                "estimated_duration_s": 5.0,
            }
        )
        
        agent = AudioGenerationAgent(output_dir=temp_output_dir)
        timeline = agent.generate_audio_timeline(sample_video_plan)
        
        # Verify timeline structure
        assert timeline["schema_version"] == "1.0.0"
        assert "created_at" in timeline
        assert "audio_timeline_id" in timeline
        assert timeline["video_plan_ref"] == "vp_test_123"
        assert timeline["duration_seconds"] == 10.0
        
        # Verify tracks
        tracks = timeline["tracks"]
        assert len(tracks) >= 2  # At least 2 voiceover tracks
        
        voiceover_tracks = [t for t in tracks if t["type"] == "voiceover"]
        assert len(voiceover_tracks) == 2
        
        # Check first voiceover track
        track1 = voiceover_tracks[0]
        assert track1["scene_id"] == "scene_01"
        assert track1["t_start_s"] == 0.0
        assert track1["t_end_s"] == 5.0
        assert track1["volume_db"] == 0
        
        # Verify TTS was called correctly
        assert mock_generate_voiceover.call_count == 2
    
    @patch('video_agent.audio_agent.generate_voiceover')
    def test_generate_audio_timeline_tts_error(
        self,
        mock_generate_voiceover,
        sample_video_plan,
        temp_output_dir
    ):
        """TTS failure uses a silent fallback; degraded issue is written to production_report."""
        import json
        mock_generate_voiceover.side_effect = TTSError("API error")

        agent = AudioGenerationAgent(output_dir=temp_output_dir)
        # Should NOT raise; instead returns a timeline with silent tracks
        timeline = agent.generate_audio_timeline(sample_video_plan)

        vo_tracks = [t for t in timeline["tracks"] if t.get("type") == "voiceover"]
        assert len(vo_tracks) > 0  # silent fallback tracks present

        report_path = temp_output_dir / "production_report.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text())
        assert report["degraded_scene_count"] > 0
        assert any(i["issue"] == "tts_failed" for i in report["issues"])
    
    def test_generate_audio_timeline_empty_scenes(self, temp_output_dir):
        """Test error when no scenes provided."""
        agent = AudioGenerationAgent(output_dir=temp_output_dir)
        
        invalid_plan = {
            "schema_version": "1.0.0",
            "scenes": []
        }
        
        with pytest.raises(AudioGenerationError, match="contains no scenes"):
            agent.generate_audio_timeline(invalid_plan)
    
    @patch('video_agent.audio_agent.generate_voiceover')
    def test_get_audio_stats(
        self,
        mock_generate_voiceover,
        sample_video_plan,
        temp_output_dir
    ):
        """Test audio statistics calculation."""
        mock_generate_voiceover.return_value = (
            temp_output_dir / "vo_test.mp3",
            {
                "character_count": 100,
                "estimated_duration_s": 5.0,
            }
        )
        
        agent = AudioGenerationAgent(output_dir=temp_output_dir)
        timeline = agent.generate_audio_timeline(sample_video_plan)
        stats = agent.get_audio_stats(timeline)
        
        assert "total_duration_s" in stats
        assert "voiceover_tracks" in stats
        assert "music_tracks" in stats
        assert "total_characters" in stats
        assert "avg_chars_per_second" in stats
        
        assert stats["voiceover_tracks"] == 2
        assert stats["total_characters"] == 200  # 100 chars * 2 scenes
    
    @patch('video_agent.audio_agent.generate_voiceover')
    def test_voice_override_from_video_plan(
        self,
        mock_generate_voiceover,
        sample_video_plan,
        temp_output_dir
    ):
        """Test that video plan can override default voice."""
        mock_generate_voiceover.return_value = (
            temp_output_dir / "vo_test.mp3",
            {"character_count": 23, "estimated_duration_s": 5.0}
        )
        
        # Override voice in video plan
        sample_video_plan["audio"]["tts"]["voice"] = "energetic"
        
        agent = AudioGenerationAgent(output_dir=temp_output_dir, voice_id="narrator")
        timeline = agent.generate_audio_timeline(sample_video_plan)
        
        # Should use energetic voice, not narrator
        assert timeline["voice_id"] == "TX3LPaxmHKxFdv7VOQHJ"  # energetic preset


class TestCreateAudioAgent:
    """Test factory function."""

    def test_create_audio_agent(self, temp_output_dir):
        """Test agent creation via factory.

        TTS_BACKEND defaults to chatterbox_server, so voice_id becomes
        "chatterbox" regardless of the voice preset passed in.
        """
        agent = create_audio_agent(
            output_dir=temp_output_dir,
            voice="calm",
            music_volume_db=-20.0
        )

        assert isinstance(agent, AudioGenerationAgent)
        assert agent.output_dir == temp_output_dir
        assert agent.voice_id == "chatterbox"
        assert agent.music_volume_db == -20.0

    def test_create_audio_agent_elevenlabs(self, temp_output_dir):
        """Test factory with elevenlabs backend resolves voice presets."""
        with patch("video_agent.audio_agent.TTS_BACKEND", "elevenlabs"):
            agent = create_audio_agent(
                output_dir=temp_output_dir,
                voice="calm",
                music_volume_db=-20.0
            )

        assert agent.voice_id == "EXAVITQu4vr4xnSDxMaL"  # calm preset
        assert agent._tts_backend is None


class TestIntegration:
    """Integration tests (require actual API key)."""
    
    @pytest.mark.skipif(
        not Path(".env").exists(),
        reason="Requires .env file with ELEVENLABS_API_KEY"
    )
    @pytest.mark.integration
    def test_real_tts_generation(self, sample_video_plan, temp_output_dir):
        """Test with real ElevenLabs API (requires API key)."""
        # Simplify to one scene to save quota
        sample_video_plan["scenes"] = sample_video_plan["scenes"][:1]
        
        agent = create_audio_agent(
            output_dir=temp_output_dir,
            voice="narrator"
        )
        
        timeline = agent.generate_audio_timeline(sample_video_plan)
        
        # Verify files were created
        assert (temp_output_dir / "audio_timeline.json").exists()
        
        # Verify at least one audio segment exists
        segments_dir = temp_output_dir / "audio_segments"
        audio_files = list(segments_dir.glob("*.mp3"))
        assert len(audio_files) > 0
        
        # Verify audio file has content
        assert audio_files[0].stat().st_size > 0
