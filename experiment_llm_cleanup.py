#!/usr/bin/env python3
"""
Quick experiment: use local Ollama (gemma3:4b) to clean up noisy transcription lines.
Reads a sample of lines from a raw transcript and asks the LLM to filter/clean them.
"""
import json, time, urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"

SYSTEM_PROMPT = """You are a transcript cleaner for a software trainer's speech-to-text recordings.
The trainer speaks Romanian and English, mixing both languages naturally.
The speech-to-text tool (Whisper) often hallucinates garbage when there is silence or background noise.

Your job: for EACH input line, output exactly one line — either cleaned speech or [SKIP].

OUTPUT RULES (strict):
- Output EXACTLY one line per input line, in the same order.
- Never merge two lines into one. Never split one line into two.
- Never add explanations, comments, or blank lines.
- Keep the timestamp prefix (e.g. "[ 2026-03-26 14:27:05.00 ]") unchanged.

ALWAYS output [SKIP] (nothing else) for these garbage patterns — Whisper hallucinates these during silence:
1. Any text containing Chinese, Japanese, Korean, Cyrillic, Arabic, or other non-Latin/Romanian scripts
2. YouTube/social media boilerplate: "subscribe", "like and comment", "Thanks for watching", "don't forget to", "follow me", "new video every"
3. Recipe / cooking instructions: ingredient lists like "1/2 tsp", "1/4 cup", "mix well", "bake at"
4. Hardware tutorial boilerplate: "disconnect the power cord", "press START/STOP", "click File > Save"
5. A single word or short phrase repeated 5+ times with no other content (e.g. "Război, război, război, război, război, război")
6. Strings of repeated characters like "e-e-e-e-e-e-e" or "r-r-r-r-r-r"
7. URLs combined with promotional text

KEEP and lightly clean real speech:
- Romanian or English sentences that make sense in a software development context
- Trainer instructions to an AI coding assistant (e.g. "vreau să...", "I want you to...", "find the file...")
- Technical questions or explanations
- If a real sentence is repeated 2-3 times, keep only one copy
- Fix obvious transcription errors but preserve the speaker's actual words and technical terms (tool names, library names, etc.)

EXAMPLES:
Input:  [ 14:27:05 ]  Reține că am railway instalat, CLI.
Output: [ 14:27:05 ]  Reține că am railway instalat, CLI.

Input:  [ 14:30:50 ]  If you have any questions please ask. If you have any questions please ask. If you have any questions please ask.
Output: [ 14:30:50 ]  If you have any questions please ask.

Input:  [ 14:37:34 ]  Disconnect the power cord from the main board. Thanks for watching and don't forget to like and subscribe!
Output: [SKIP]

Input:  [ 14:35:46 ]  Război, război, război, război, război, război, război, război, război, război,
Output: [SKIP]

Input:  [ 14:37:58 ]  1/2 茶 (4g)  1/2 茶 (4g)  1/2 茶 (4g)
Output: [SKIP]

Input:  [ 14:40:15 ]  真を見るためにスマートフォンを使用して字幕を作成する必要があります。
Output: [SKIP]

Input:  [ 14:36:27 ]  Ideea este, mi-ar trebui să-i pot da două surse de input la care să asculte.
Output: [ 14:36:27 ]  Ideea este, mi-ar trebui să-i pot da două surse de input la care să asculte.
"""

# A sample of lines mixing real content and noise
SAMPLE_LINES = [
    "[ 2026-03-26 14:27:05.00 ]  Reține că am railway instalat, CLI.",
    "[ 2026-03-26 14:27:28.00 ]  Select the path you want to run and click on it to run it.️ Follow me: http://bit.ly/ISCVideo New HD video every 2 Days,",
    "[ 2026-03-26 14:28:05.00 ]  O prăștește pentru moment.",
    "[ 2026-03-26 14:28:36.00 ]  Comentează, nu șterge codul. Cel care face conversia automată din PowerPoint în PDF, din daemon. Repede puși pe master. Acum începeți discuția.",
    "[ 2026-03-26 14:29:40.00 ]  Vreau să găsești Powerpoint-ul de iCoding și să-l convertești în PDF în folderul de materiale cu ajutorul Powerpoint controlând aplicația, să văd cum se simte.",
    "[ 2026-03-26 14:30:50.00 ]  If you have any questions, please feel free to ask in the comments section. If you have any questions, please feel free to ask in the comments section. If you have any questions, please feel free to ask in the comments section.",
    "[ 2026-03-26 14:35:46.00 ]  Război, război, război, război, război, război, război, război, război, război, război, război, război, război, război, război,",
    "[ 2026-03-26 14:36:09.00 ]  Îl pot lega de o sursă de audio ca loopback, pot să-l fac să asculte acolo și pot să-l leg de acolo și pot să-l fac să-l asculte de acolo și pot să-l fac să-l asculte de acolo și pot să-l fac să-l asculte de acolo.",
    "[ 2026-03-26 14:36:27.00 ]  Ideea este, mi-ar trebui să-i pot da două surse de input la care să asculte, ca să distingă între ce pronunț eu și ce pronunță interlocutorul meu într-o ședință.",
    "[ 2026-03-26 14:37:34.00 ]  Disconnect the power cord from the main board. Thanks for watching and don't forget to like and subscribe!",
    "[ 2026-03-26 14:37:58.00 ]  1/2 茶 (4g)  1/2 茶 (4g)  1/2 茶 (4g)  1/2 茶 (4g) ",
    "[ 2026-03-26 14:38:22.00 ]  Vreau sa va arat ca ori de cate ori vrei sa faci o schimbare in daemon, trebuie sa faci push pe master pentru ca daemon o face pull continuu de pe master si roleaza orice schimbare pe ea acolo.",
    "[ 2026-03-26 14:39:22.00 ]  Ce înseamnă 'Speaker Deactivation' și 'Voice Activity Detection'? Și aș putea să-i trimit lui WhisperKit două stream-uri audio unei singure instanțe care transcrie?",
    "[ 2026-03-26 14:40:15.00 ]  真を見るためにスマートフ\u30a9ンを使用して字幕を作成する必要があります。スマートフ\u30a9ンを使用して字幕を作成する必要があります。",
    "[ 2026-03-26 14:32:42.00 ]  Conversiunea de transcripție pentru execuție locală pe Mac OS",
    "[ 2026-03-26 14:33:27.00 ]  care o să-mi facă Live Transcribe, imediat ce poate înțelege ce s-a vorbit, o precizie cât mai mare, o latență de maxim, nu știu, 10 secunde după ce s-a vorbit, s-a vorbit local, Mac-ul este M1 silicon.",
]

def clean_line(line: str) -> str:
    payload = {
        "model": MODEL,
        "system": SYSTEM_PROMPT,
        "prompt": line,
        "stream": False,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(OLLAMA_URL, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["response"].strip()

print(f"{'INPUT':<70}  {'OUTPUT'}")
print("-" * 120)
t0 = time.time()
skipped = kept = 0
for line in SAMPLE_LINES:
    result = clean_line(line)
    # truncate for display
    inp = line[25:].strip()[:65]  # strip timestamp for brevity
    out = result[25:].strip()[:65] if result != "[SKIP]" else "[SKIP]"
    marker = "✓" if result != "[SKIP]" else "✗"
    print(f"{marker} {inp:<68}  {out}")
    if result == "[SKIP]":
        skipped += 1
    else:
        kept += 1

elapsed = time.time() - t0
print(f"\n--- {kept} kept, {skipped} skipped | {elapsed:.1f}s total ({elapsed/len(SAMPLE_LINES):.1f}s/line) ---")
