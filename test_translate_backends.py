import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Test each backend
print("=" * 50)
print("Testing translation backends")
print("=" * 50)

# 1. Youdao
print("\n1. Youdao (mobile endpoint):")
try:
    from modules.mcp_translate import _translate_youdao
    t0 = time.time()
    result = _translate_youdao("Hello World, how are you today?", "zh", "auto")
    elapsed = time.time() - t0
    print(f"   [{elapsed:.1f}s] PASS: {result[:120]}")
except Exception as e:
    print(f"   FAIL: {e}")

# 2. MyMemory
print("\n2. MyMemory:")
try:
    from modules.mcp_translate import _translate_mymemory
    t0 = time.time()
    result = _translate_mymemory("Hello World, how are you today?", "zh", "auto")
    elapsed = time.time() - t0
    print(f"   [{elapsed:.1f}s] PASS: {result[:120]}")
except Exception as e:
    print(f"   FAIL: {e}")

# 3. Google
print("\n3. Google (multi-domain):")
try:
    from modules.mcp_translate import _translate_google_cn
    t0 = time.time()
    result = _translate_google_cn("Hello World", "zh", "auto")
    elapsed = time.time() - t0
    print(f"   [{elapsed:.1f}s] PASS: {result[:120]}")
except Exception as e:
    print(f"   FAIL: {e}")

# 4. Argos
print("\n4. Argos (offline):")
try:
    from modules.mcp_translate import _translate_argos
    t0 = time.time()
    result = _translate_argos("Hello World", "zh", "en")
    elapsed = time.time() - t0
    print(f"   [{elapsed:.1f}s] PASS: {result[:120]}")
except Exception as e:
    print(f"   FAIL: {e}")

# 5. Language detection
print("\n5. Language detection:")
try:
    from modules.mcp_translate import _exec_detect
    result = _exec_detect({"text": "Hello World, this is a test"})
    print(f"   PASS: {result[:150]}")
except Exception as e:
    print(f"   FAIL: {e}")

# 6. Test the full translate flow via API
print("\n\n" + "=" * 50)
print("Testing via /api/chat endpoint")
print("=" * 50)

import json, requests
API = "http://localhost:5000/api/chat"
API_KEY = ""
API_BASE = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"

all_tools = requests.get("http://localhost:5000/api/tools/definitions").json()
tool_index = {t["function"]["name"]: t for t in all_tools}

tests = [
    ("translate en->zh", ["translate_text"], "Translate 'Good morning, nice to meet you' to Chinese", 3),
    ("detect language", ["detect_language"], "What language is 'Bonjour le monde'?", 3),
    ("translate zh->en", ["translate_text"], "把今天天气真好翻译成英文", 3),
]

for label, tool_names, prompt, max_r in tests:
    test_tools = [{"type": "function", "function": tool_index[t]["function"]}
                  for t in tool_names if t in tool_index]

    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "model": MODEL, "api_base": API_BASE, "api_key": API_KEY,
        "tools": test_tools, "max_tool_rounds": max_r,
        "max_tokens": 1024, "temperature": 0.1, "stream": False
    }

    try:
        t0 = time.time()
        resp = requests.post(API, json=payload, timeout=60)
        elapsed = time.time() - t0

        calls = []; tool_results = []; errors = []
        for line in resp.text.split('\n'):
            if not line.startswith('data: '): continue
            ds = line[6:]
            if ds == '[DONE]': break
            try: d = json.loads(ds)
            except: continue
            if d.get('error'): errors.append(d['error'])
            if d.get('tool_calls'):
                for tc in d['tool_calls']: calls.append(tc['name'])
            if d.get('tool_result'):
                tr = d['tool_result']
                tool_results.append({"name": tr['name'], "result": tr['result'][:250]})

        ok = len(calls) > 0 and not errors
        print(f"\n  [{('PASS' if ok else 'FAIL')}] {label} ({elapsed:.1f}s)")
        print(f"  Calls: {calls}")
        for tr in tool_results:
            print(f"  [{tr['name']}]: {tr['result'][:180]}")
        if errors:
            for e in errors:
                print(f"  ERROR: {e[:150]}")

    except Exception as e:
        print(f"\n  [FAIL] {label}: {e}")
