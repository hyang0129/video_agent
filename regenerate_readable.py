"""Regenerate script_readable.txt from script_package.json"""

import json
from pathlib import Path
import sys

if len(sys.argv) < 2:
    print("Usage: python regenerate_readable.py <path_to_script_package.json>")
    print("\nExample:")
    print('  python regenerate_readable.py "results/star_wars_pipeline_20260210_140900/script_package.json"')
    sys.exit(1)

script_path = Path(sys.argv[1])
if not script_path.exists():
    print(f"Error: File not found: {script_path}")
    sys.exit(1)

# Load script package
with open(script_path, 'r', encoding='utf-8') as f:
    script_package = json.load(f)

script = script_package.get('script', {})
has_body_format = 'body' in script and 'hook' in script

# Build voiceover text
if has_body_format:
    vo_parts = []
    if script.get('hook'):
        vo_parts.append(script['hook'])
    vo_parts.extend([seg.get('content', '') for seg in script.get('body', [])])
    if script.get('call_to_action'):
        vo_parts.append(script['call_to_action'])
    vo_text = ' '.join(vo_parts)
else:
    vo_text = script.get('voiceover', '')

# Get hashtags
hashtags = script_package.get('hashtags', [])

# Generate readable file
output_path = script_path.parent / "script_readable.txt"
with open(output_path, 'w', encoding='utf-8') as f:
    f.write("STAR WARS FACTS - FACT-GROUNDED SCRIPT\n")
    f.write("=" * 80 + "\n\n")
    f.write(f"Script ID: {script_package.get('script_package_id', 'N/A')}\n")
    f.write(f"Facts Used: {len(script_package.get('fact_sources', []))}\n\n")
    
    if has_body_format:
        # Write fact-grounded format
        f.write("=" * 80 + "\n")
        f.write("HOOK:\n")
        f.write("=" * 80 + "\n")
        f.write(script.get('hook', '') + "\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("FACT-BASED CONTENT:\n")
        f.write("=" * 80 + "\n\n")
        
        for i, segment in enumerate(script.get('body', []), 1):
            f.write(f"Segment {i}:\n")
            f.write(f"{segment.get('content', '')}\n")
            if segment.get('fact_ids'):
                f.write(f"Facts: {', '.join(segment['fact_ids'])}\n")
            f.write("\n")
        
        f.write("=" * 80 + "\n")
        f.write("CALL TO ACTION:\n")
        f.write("=" * 80 + "\n")
        f.write(script.get('call_to_action', '') + "\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("FULL VOICEOVER:\n")
        f.write("=" * 80 + "\n")
        f.write(vo_text + "\n\n")
    else:
        beats = script.get('beats', [])
        # Write beat-based format
        f.write("HOOKS:\n")
        for i, hook in enumerate(script_package.get('hook_variants', []), 1):
            f.write(f"  {i}. {hook}\n")
        
        f.write("\n" + "=" * 80 + "\n")
        f.write("FULL VOICEOVER:\n")
        f.write("=" * 80 + "\n")
        f.write(vo_text + "\n")
        
        f.write("\n" + "=" * 80 + "\n")
        f.write("BEAT-BY-BEAT BREAKDOWN:\n")
        f.write("=" * 80 + "\n\n")
        
        for i, beat in enumerate(beats, 1):
            f.write(f"Beat {i} [{beat.get('t_start_s', 0):.1f}s - {beat.get('t_end_s', 0):.1f}s]\n")
            f.write(f"  On-Screen: {beat.get('on_screen_text', '')}\n")
            f.write(f"  Voiceover: {beat.get('vo_line', '')}\n\n")
    
    f.write("=" * 80 + "\n")
    f.write(f"Caption: {script_package.get('caption', '')}\n")
    if hashtags:
        f.write(f"Hashtags: {' '.join(hashtags)}\n")

print(f"✓ Regenerated: {output_path}")
print(f"\nFormat detected: {'FACT-GROUNDED (body/hook format)' if has_body_format else 'BEATS FORMAT'}")
print(f"Facts used: {len(script_package.get('fact_sources', []))}")
