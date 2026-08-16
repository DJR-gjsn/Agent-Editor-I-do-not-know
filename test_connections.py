import json, time, requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API = "http://localhost:5000/api/chat"
API_KEY = ""
API_BASE = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"

with open('D:/myxiangfa-MCPxuexi/data/projects/proj_b3f7d16fb5.json','r',encoding='utf-8') as f:
    proj = json.load(f)

comps = {c['id']: c for c in proj['layout']['components']}
conns = proj['layout']['connections']

connected_comps = {}
for conn in conns:
    if conn['sourceCompId'] == 1:
        tgt = comps.get(conn['targetCompId'])
        if tgt and tgt['type'] != 'llm':
            connected_comps[tgt['id']] = tgt

print(f"Project has {len(connected_comps)} components connected to LLM\n")

comp_tool_names = {
    'web_search': ['web_search'],
    'calculator': ['calculator'],
    'time_query': ['get_current_time'],
    'url_fetch': ['url_fetch'],
    'code_executor': ['code_executor'],
    'text_tools': ['text_analyze', 'text_format'],
    'mcp_word': ['word_create', 'word_add_heading', 'word_add_paragraph', 'word_add_table', 'word_save'],
    'mcp_excel': ['excel_create', 'excel_write_cell', 'excel_read_cell', 'excel_add_sheet', 'excel_save'],
    'mcp_ppt': ['ppt_create', 'ppt_add_slide', 'ppt_add_text', 'ppt_add_bullet_list', 'ppt_save'],
    'mcp_pdf': ['pdf_read', 'pdf_create', 'pdf_merge'],
    'file_ops': ['file_read', 'file_write', 'file_edit', 'glob_search', 'grep_search'],
    'json_query': ['json_query'],
    'mcp_encoding': ['base64_encode', 'base64_decode', 'hash_compute', 'password_generate', 'uuid_generate', 'regex_test', 'diff_text', 'markdown_to_html', 'html_to_markdown', 'unit_convert', 'url_encode'],
    'mcp_translate': ['translate_text', 'detect_language'],
    'mcp_weather': ['weather_current', 'weather_forecast'],
    'mcp_geocode': ['geocode_address', 'reverse_geocode', 'ip_geolocation', 'distance_calc'],
    'mcp_system': ['system_info', 'dns_lookup', 'qr_generate', 'open_file', 'desktop_notify'],
    'mcp_clipboard': ['clipboard_read', 'clipboard_write'],
    'memory_summarizer': ['memory_summarize'],
    'plan': ['plan_generate', 'plan_execute_step'],
    'executor': ['executor_run'],
    'mcp_finance': ['currency_convert', 'stock_price'],
    'mcp_calendar': ['calendar_list', 'calendar_create'],
    'mcp_database': ['db_query', 'db_list_tables', 'db_schema'],
    'mcp_git': ['git_status', 'git_log', 'git_diff', 'git_branch'],
    'mcp_navigation': ['nav_route', 'nav_search_place'],
    'mcp_email': ['email_send'],
}

all_tools = requests.get("http://localhost:5000/api/tools/definitions").json()
tool_index = {t["function"]["name"]: t for t in all_tools}

test_prompts = {
    'web_search': "search for Python latest version",
    'calculator': "calculate 123*456",
    'time_query': "what time is it now",
    'url_fetch': "fetch https://httpbin.org/json",
    'code_executor': "use Python to sum 1 to 100",
    'text_tools': "analyze word count of: hello world test",
    'mcp_word': "create a Word doc titled Test",
    'mcp_excel': "create Excel, write test in A1",
    'mcp_ppt': "create a PPT titled Test",
    'mcp_pdf': "convert Hello World to PDF",
    'file_ops': "create file test.txt with content auto-test",
    'json_query': "extract field a from JSON {\"a\":1}",
    'mcp_encoding': "compute MD5 hash of hello",
    'mcp_translate': "translate hello to Chinese",
    'mcp_weather': "check Beijing weather",
    'mcp_geocode': "lookup IP 8.8.8.8 location",
    'mcp_system': "get system info",
    'mcp_clipboard': "read clipboard",
    'memory_summarizer': "summarize: user asked about sort, AI gave bubble sort",
    'plan': "make a 3-step plan for writing annual report",
    'executor': "execute: step1 calculate 1+1",
    'mcp_finance': "convert 100 USD to CNY",
    'mcp_calendar': "list today calendar",
    'mcp_database': "list database tables",
    'mcp_git': "check git status",
    'mcp_navigation': "search nearby restaurants",
    'mcp_email': "send test email to test@example.com",
}

results = {}
for comp_id, comp in sorted(connected_comps.items()):
    comp_type = comp['type']
    tool_names = comp_tool_names.get(comp_type, [])
    if not tool_names:
        continue

    primary_tool = tool_names[0]
    if primary_tool not in tool_index:
        results[comp_type] = {"status": "SKIP", "detail": f"tool not registered"}
        continue

    test_tools = [{"type": "function", "function": tool_index[t]["function"]}
                  for t in tool_names if t in tool_index]

    prompt = test_prompts.get(comp_type, f"use {tool_names[0]} tool")

    print(f"{'='*50}")
    print(f"Testing [{comp_id}] {comp_type} -> {tool_names[:3]}...")

    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "model": MODEL, "api_base": API_BASE, "api_key": API_KEY,
        "tools": test_tools, "max_tool_rounds": 5,
        "max_tokens": 2048, "temperature": 0.1, "stream": False
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
                tool_results.append({"name": tr['name'], "result": tr['result'][:300]})
            if d.get('choices'):
                c = d['choices'][0].get('delta',{}).get('content','')
                if c: content += c

        status = "PASS"
        detail = ""
        if errors:
            status = "FAIL"; detail = errors[0][:150]
        elif not calls:
            status = "FAIL"; detail = "no tool calls: " + content[:80]
        else:
            for tr in tool_results:
                r = tr["result"]
                if any(kw in r for kw in ['Error:', 'Connection refused', 'Traceback', 'AttributeError',
                    'ModuleNotFoundError', 'API_KEY', 'not configured', 'latin-1']):
                    status = "FAIL"; detail = r[:200]; break
            if status == "PASS":
                detail = "called " + ", ".join(calls)

        results[comp_type] = {"status": status, "elapsed": round(elapsed,1), "detail": detail,
                            "calls": calls}
        print(f"  [{status}] ({elapsed:.1f}s) {detail[:120]}")
        for tr in tool_results:
            print(f"    [{tr['name']}]: {tr['result'][:150]}")

    except Exception as e:
        results[comp_type] = {"status": "FAIL", "detail": str(e)[:200]}
        print(f"  [FAIL] {e}")

print(f"\n\n{'='*60}")
print("PROJECT CONNECTION TEST RESULTS")
print(f"{'='*60}")
pass_c = fail_c = skip_c = 0
for ctype, r in sorted(results.items()):
    s = r["status"]
    if s == "PASS": pass_c += 1
    elif s == "FAIL": fail_c += 1
    else: skip_c += 1
    icon = "PASS" if s == "PASS" else ("FAIL" if s == "FAIL" else "SKIP")
    elapsed = r.get("elapsed", 0)
    print(f"  [{icon}] {ctype:25s} | {str(elapsed):>5s}s | {r['detail'][:100]}")

print(f"\nTotal: {pass_c} pass, {fail_c} fail, {skip_c} skip (out of {len(results)})")

with open("D:/myxiangfa-MCPxuexi/test_project_connections.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
