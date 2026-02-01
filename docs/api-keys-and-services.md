# Video Production Pipeline - API Keys & Services

## Required API Services

This document outlines all external services and API keys needed for the video production pipeline.

---

## 1. Audio Agent APIs

### Text-to-Speech (TTS)

#### Option A: ElevenLabs (Recommended)
- **Service**: Premium TTS with natural voices
- **Pricing**: $5/month starter (30,000 chars), $22/month creator (100,000 chars)
- **API Key**: `ELEVENLABS_API_KEY`
- **Endpoint**: `https://api.elevenlabs.io/v1/text-to-speech`
- **Features**: 
  - High-quality, natural-sounding voices
  - Emotion and tone control
  - Multiple language support
  - Voice cloning capabilities
- **Rate Limits**: Depends on plan tier
- **Documentation**: https://docs.elevenlabs.io/

#### Option B: Azure Cognitive Services Speech
- **Service**: Microsoft TTS
- **Pricing**: $15 per 1M characters (Standard), $105 per 1M (Neural)
- **API Key**: `AZURE_SPEECH_KEY` + `AZURE_SPEECH_REGION`
- **Endpoint**: `https://<region>.tts.speech.microsoft.com/cognitiveservices/v1`
- **Features**:
  - Wide language support
  - Neural voices available
  - SSML support for precise control
  - Good for enterprise/scale
- **Rate Limits**: 200 TPS per subscription
- **Documentation**: https://learn.microsoft.com/en-us/azure/cognitive-services/speech-service/

#### Option C: Google Cloud Text-to-Speech
- **Service**: Google TTS
- **Pricing**: $4 per 1M characters (Standard), $16 per 1M (WaveNet/Neural2)
- **API Key**: `GOOGLE_APPLICATION_CREDENTIALS` (JSON key file path)
- **Features**:
  - Wavenet voices sound natural
  - SSML support
  - Good integration if already using Google services
- **Rate Limits**: 600 requests/minute
- **Documentation**: https://cloud.google.com/text-to-speech

**Recommendation**: Start with **ElevenLabs** for quality, switch to Azure/Google if scaling costs require it.

---

### Sound Effects

#### Option A: Freesound API (Free)
- **Service**: Community sound library
- **Pricing**: Free (requires attribution)
- **API Key**: `FREESOUND_API_KEY`
- **Endpoint**: `https://freesound.org/apiv2/`
- **Features**:
  - Large library of user-uploaded sounds
  - Search by tags, description
  - Creative Commons licensed
- **Rate Limits**: 60 requests/minute (OAuth: 120 req/min)
- **Documentation**: https://freesound.org/docs/api/

#### Option B: Epidemic Sound API
- **Service**: Professional stock audio
- **Pricing**: $15/month (personal), custom pricing for commercial
- **API Key**: `EPIDEMIC_SOUND_API_KEY`
- **Features**:
  - Professional quality
  - Licensed for commercial use
  - Large SFX library
- **Documentation**: Contact for API access

**Recommendation**: Start with **Freesound** for prototype, upgrade to Epidemic Sound for production.

---

### Background Music

#### Current Approach (Phase 1): Placeholder Track
- **Music File**: `assets/default_music.mp3`
- **Track**: "Pixel Peeker Polka - slower" by Kevin MacLeod
- **License**: Creative Commons Attribution 4.0
- **Source**: https://incompetech.com/
- **Pricing**: Free (attribution required)
- **Features**:
  - Upbeat, energetic
  - Works well for educational/informative content
  - No API needed
  - Attribution in video description: "Music: Pixel Peeker Polka - slower by Kevin MacLeod (incompetech.com) Licensed under Creative Commons: By Attribution 4.0 License"

#### Future Options (Phase 2): Dynamic Music Selection

**Option A: Epidemic Sound**
- **Pricing**: $15/month (personal), $49/month (commercial)
- **API Key**: `EPIDEMIC_SOUND_API_KEY`
- **Features**: 40,000+ tracks, cleared for social media

**Option B: Soundstripe**
- **Pricing**: $15/month (music only), $30/month (music + SFX)
- **Features**: Unlimited downloads, simple licensing

**Option C: AI-Generated Music**
- Services: Soundraw ($20/month), AIVA ($15/month), Mubert ($14/month)
- **Advantage**: No attribution needed, unique tracks

**Recommendation for Phase 2**: Epidemic Sound for API integration or AI-generated for uniqueness.

---

## 2. Visual Agent APIs

### Stock Images

#### Option A: Pexels API (Free - Recommended)
- **Service**: Free stock photos
- **Pricing**: Free
- **API Key**: `PEXELS_API_KEY`
- **Endpoint**: `https://api.pexels.com/v1/`
- **Features**:
  - High-quality images
  - No attribution required
  - Good search functionality
  - Orientation filtering
- **Rate Limits**: 200 requests/hour
- **Documentation**: https://www.pexels.com/api/

#### Option B: Unsplash API (Free)
- **Service**: Free stock photos
- **Pricing**: Free (50 requests/hour), $10/month (500 req/hr)
- **API Key**: `UNSPLASH_ACCESS_KEY` + `UNSPLASH_SECRET_KEY`
- **Endpoint**: `https://api.unsplash.com/`
- **Features**:
  - Very high-quality images
  - Requires attribution
  - Popular with designers
- **Rate Limits**: 50 requests/hour (free)
- **Documentation**: https://unsplash.com/documentation

#### Option C: Pixabay API (Free)
- **Service**: Free stock media
- **Pricing**: Free
- **API Key**: `PIXABAY_API_KEY`
- **Features**:
  - Images + videos + illustrations
  - No attribution required
  - Good variety
- **Rate Limits**: None specified
- **Documentation**: https://pixabay.com/api/docs/

**Recommendation**: Use **Pexels** as primary, **Unsplash** and **Pixabay** as fallbacks.

---

### AI Image Generation

#### Option A: OpenAI DALL-E 3 (Recommended)
- **Service**: AI image generation
- **Pricing**: $0.040 per image (standard 1024×1024), $0.080 (HD)
- **API Key**: `OPENAI_API_KEY`
- **Endpoint**: `https://api.openai.com/v1/images/generations`
- **Features**:
  - High quality, follows prompts well
  - Multiple sizes (1024×1024, 1792×1024, 1024×1792)
  - Good for custom visuals
- **Rate Limits**: 50 images/minute (tier 1)
- **Documentation**: https://platform.openai.com/docs/guides/images

#### Option B: Stability AI (Stable Diffusion)
- **Service**: Open-source AI image generation
- **Pricing**: $10/month (3,000 credits)
- **API Key**: `STABILITY_API_KEY`
- **Endpoint**: `https://api.stability.ai/`
- **Features**:
  - Very customizable
  - Multiple models (SD 1.5, SDXL)
  - Style presets available
- **Rate Limits**: Depends on plan
- **Documentation**: https://platform.stability.ai/docs

#### Option C: Midjourney (No official API)
- **Note**: No official API yet (as of Feb 2026)
- Requires Discord bot interaction (not production-ready)

**Recommendation**: **OpenAI DALL-E 3** for quality and ease of use.

---

### Stock Video Clips (Phase 2)

#### Option A: Pexels Videos API (Free)
- **Service**: Free stock videos
- **Pricing**: Free
- **API Key**: `PEXELS_API_KEY` (same as images)
- **Endpoint**: `https://api.pexels.com/videos/`
- **Features**:
  - HD/4K videos
  - No attribution required
  - Duration filtering
- **Rate Limits**: 200 requests/hour
- **Documentation**: https://www.pexels.com/api/

#### Option B: Pixabay Videos API (Free)
- **Service**: Free stock videos
- **Pricing**: Free
- **API Key**: `PIXABAY_API_KEY`
- **Features**: Similar to Pexels
- **Documentation**: https://pixabay.com/api/docs/

**Recommendation**: **Pexels** for video clips when ready for Phase 2.

---

### AI Video Generation (Phase 3)

#### Option A: Runway Gen-2
- **Service**: AI video generation
- **Pricing**: $12/month (125 credits), $28/month (625 credits)
- **API Key**: Waitlist for API access
- **Features**:
  - Text-to-video
  - Image-to-video
  - 4-second clips
- **Status**: API in limited beta

#### Option B: Pika Labs
- **Service**: AI video generation
- **Pricing**: TBD (currently Discord bot only)
- **Status**: No API yet

**Recommendation**: Wait until APIs mature (not needed for Phase 1).

---

## 3. Compositor Agent Dependencies

### Video Processing Libraries

#### FFmpeg (Open Source)
- **Service**: Video encoding/processing
- **Pricing**: Free
- **Installation**: System package (no API key)
- **Features**:
  - Industry standard
  - Handles all formats
  - Command-line interface
- **Usage**: Via subprocess calls
- **Documentation**: https://ffmpeg.org/

#### MoviePy (Python Library)
- **Service**: Python video editing
- **Pricing**: Free (MIT license)
- **Installation**: `pip install moviepy`
- **Features**:
  - Pythonic API over FFmpeg
  - Easy compositing
  - Text/effects support
- **Documentation**: https://zulko.github.io/moviepy/

**No API keys required** - these are local processing tools.

---

## 4. Current Project APIs (Already Configured)

### Google Gemini (LangChain)
- **Usage**: Agent reasoning and decision-making
- **API Key**: `GOOGLE_API_KEY` (already in use)
- **Model**: `gemini-flash-latest`
- **Cost**: Free tier available, then pay-as-you-go
- **Note**: Already configured for market research and script generation

### YouTube Data API v3
- **Usage**: Content research (existing functionality)
- **API Key**: `YOUTUBE_API_KEY` (already in use)
- **Note**: Already configured for market research agent

---

## Summary: Minimum Required APIs for Phase 1

To get started with the image slideshow pipeline, you need:

### Essential (Minimum Viable Product)
1. **TTS**: ElevenLabs API key (`ELEVENLABS_API_KEY`)
   - Alternative: Azure Speech (`AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`)
2. **Images**: Pexels API key (`PEXELS_API_KEY`) - Free
3. **Music**: Placeholder track (included in repo) - Free
   - Default: Kevin MacLeod CC BY 4.0 track
4. **Local**: FFmpeg installed on system (free)

### Recommended (Better Quality)
5. **SFX**: Freesound API key (`FREESOUND_API_KEY`) - Free
6. **AI Images**: OpenAI API key (`OPENAI_API_KEY`) - for custom visuals
7. **Fallback Images**: Unsplash API key (`UNSPLASH_ACCESS_KEY`) - Free

### Total Estimated Monthly Cost (Phase 1)
- **Minimum**: ~$5/month (ElevenLabs starter plan only)
- **Recommended**: ~$15-25/month (add some OpenAI credits for custom images)
- **Phase 2**: Add ~$15-50/month for music API when needed

---

## Environment Variables Setup

Add to `.env` file:

```bash
# === Existing APIs ===
GOOGLE_API_KEY=your_gemini_key
YOUTUBE_API_KEY=your_youtube_key

# === Audio APIs ===
# TTS (choose one)
ELEVENLABS_API_KEY=your_elevenlabs_key
# OR
AZURE_SPEECH_KEY=your_azure_key
AZURE_SPEECH_REGION=eastus

# Sound Effects (Phase 2)
# FREESOUND_API_KEY=your_freesound_key

# Music (Phase 2 - using placeholder for now)
# EPIDEMIC_SOUND_API_KEY=your_epidemic_key

# === Visual APIs ===
# Stock Images (all recommended for fallbacks)
PEXELS_API_KEY=your_pexels_key
UNSPLASH_ACCESS_KEY=your_unsplash_key
PIXABAY_API_KEY=your_pixabay_key

# AI Image Generation
OPENAI_API_KEY=your_openai_key
STABILITY_API_KEY=your_stability_key
```

Update `src/config.py` to load these keys.

---

## Next Steps

1. ✅ Review API options and select preferred services
2. ✅ Sign up for accounts and obtain API keys
3. ✅ Update `.env` with keys
4. ✅ Update `src/config.py` to load new keys
5. ✅ Begin implementation with Orchestrator Agent
