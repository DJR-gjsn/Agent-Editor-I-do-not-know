import json, time, requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API = "http://localhost:5000/api/chat"
API_KEY = ""
API_BASE = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"

# Get skills
skills = requests.get("http://localhost:5000/api/skills").json()
print(f"Testing {len(skills)} skills via smart mode\n")

results = {}

# Test each skill via proper smart mode
skill_tests = {
    "document": "I need to create a Word document to record meeting minutes",
    "frontend-design": "Help me design a login page UI style",
    "ui-ux-pro-max": "Design UX for an e-commerce product detail page",
    "find-skills": "Are there any skills for code review?",
    "skill-creator": "I want to create a new code formatting skill",
    "superpowers": "Help me analyze the quality of this code: def foo(x): return x+1",
    "pua": "I'm starting a project, give me execution advice",
}

for skill_id, prompt in skill_tests.items():
    skill_info = next((s for s in skills if s['id'] == skill_id), None)
    if not skill_info:
        continue

    print(f"{'='*50}")
    print(f"Testing: {skill_id} ({skill_info['name']})")
    print(f"Prompt: {prompt}")

    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "model": MODEL, "api_base": API_BASE, "api_key": API_KEY,
        "smart_mode": True,
        "available_skills": [{"id": skill_id, "name": skill_info['name']}],
        "max_tool_rounds": 5, "max_tokens": 2048, "temperature": 0.3, "stream": False
    }

    try:
        t0 = time.time()
        resp = requests.post(API, json=payload, timeout=120)
        elapsed = time.time() - t0

        calls = []; tool_results = []; errors = []; content = ""
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
            if d.get('choices'):
                c = d['choices'][0].get('delta',{}).get('content','')
                if c: content += c

        # Analyze
        use_skill_called = "use_skill" in calls
        skill_result_ok = False
        skill_prompt_len = 0
        for tr in tool_results:
            if tr['name'] == 'use_skill':
                r = tr['result']
                skill_prompt_len = len(r)
                if 'not found' not in r.lower() and r:
                    skill_result_ok = True

        status = "PASS"
        detail = ""
        if errors:
            status = "FAIL"; detail = errors[0][:120]
        elif use_skill_called and skill_result_ok:
            detail = f"skill activated ({skill_prompt_len} chars), called: {calls}"
        elif use_skill_called and not skill_result_ok:
            status = "FAIL"; detail = f"use_skill returned empty/error"
        elif not use_skill_called and content:
            detail = f"no use_skill, direct reply: {content[:80]}"
        else:
            status = "FAIL"; detail = "no tool calls and no content"

        results[skill_id] = {
            "status": status, "elapsed": round(elapsed,1),
            "calls": calls, "skill_prompt_len": skill_prompt_len,
            "detail": detail
        }
        print(f"  [{status}] ({elapsed:.1f}s) {detail}")
        for tr in tool_results:
            print(f"    [{tr['name']}]: {tr['result'][:180]}")

    except Exception as e:
        results[skill_id] = {"status": "FAIL", "detail": str(e)[:120]}
        print(f"  [FAIL] {e}")

# Step 2: Test multi-skill (smart mode with 3 skills available)
print(f"\n{'='*60}")
print("STEP 2: Smart mode with multiple skills available")

multi_payload = {
    "messages": [{"role": "user", "content": "I need to write a project report as a Word document, with high execution standards"}],
    "model": MODEL, "api_base": API_BASE, "api_key": API_KEY,
    "smart_mode": True,
    "available_skills": [
        {"id": "document", "name": "Document Expert"},
        {"id": "pua", "name": "PUA Coach"},
        {"id": "superpowers", "name": "Superpowers"},
    ],
    "max_tool_rounds": 10, "max_tokens": 2048, "temperature": 0.3, "stream": False
}

try:
    t0 = time.time()
    resp = requests.post(API, json=multi_payload, timeout=180)
    elapsed = time.time() - t0

    calls = []; tool_results = []; errors = []; content = ""
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
            tool_results.append({"name": tr['name'], "result": tr['result'][:200]})
        if d.get('choices'):
            c = d['choices'][0].get('delta',{}).get('content','')
            if c: content += c

    use_skill_calls = [c for c in calls if c == 'use_skill']
    other_calls = [c for c in calls if c != 'use_skill']

    status = "PASS" if (use_skill_calls or other_calls) and not errors else "FAIL"

    results["multi_skill"] = {
        "status": status, "elapsed": round(elapsed,1),
        "use_skill_calls": len(use_skill_calls), "other_calls": other_calls,
    }
    print(f"  [{status}] ({elapsed:.1f}s)")
    print(f"  use_skill calls: {len(use_skill_calls)}")
    print(f"  Other tool calls: {other_calls}")
    for tr in tool_results[:5]:
        print(f"    [{tr['name']}]: {tr['result'][:150]}")

except Exception as e:
    results["multi_skill"] = {"status": "FAIL", "detail": str(e)[:120]}
    print(f"  [FAIL] {e}")

# Summary
print(f"\n\n{'='*60}")
print("SKILLS TEST RESULTS")
print(f"{'='*60}")
pass_c = fail_c = 0
for sid, r in sorted(results.items()):
    s = r["status"]
    icon = "PASS" if s == "PASS" else "FAIL"
    if s == "PASS": pass_c += 1
    else: fail_c += 1
    elapsed = r.get("elapsed", 0)
    detail = r.get("detail", str(r.get("calls", r.get("other_calls", ""))))
    print(f"  [{icon}] {sid:30s} | {str(elapsed):>5s}s | {detail[:100]}")

print(f"\nTotal: {pass_c} pass, {fail_c} fail out of {len(results)}")

with open("D:/myxiangfa-MCPxuexi/test_skills_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
