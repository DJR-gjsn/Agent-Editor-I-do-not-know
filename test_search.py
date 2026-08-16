"""Quick test of Baidu web search parsing"""
import requests, re, time
from lxml import etree

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
}

def test_baidu_web(query):
    """Test if Baidu web search is accessible and parseable"""
    url = "https://www.baidu.com/s"
    params = {"wd": query, "rn": 10}

    t0 = time.time()
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        elapsed = time.time() - t0
        print(f"\nBaidu: {query} (HTTP {r.status_code}, {len(r.text)} bytes, {elapsed:.1f}s)")

        if r.status_code != 200 or len(r.text) < 5000:
            print("  FAIL: response too short or bad status")
            return

        tree = etree.HTML(r.text)
        # Try multiple selectors for Baidu results
        for sel in ['//div[contains(@class,"result")]', '//div[contains(@class,"c-container")]',
                     '//div[@tpl]', '//div[contains(@class,"cr-content")]']:
            items = tree.xpath(sel)
            if items:
                print(f"  Selector '{sel}': {len(items)} items")
                for item in items[:3]:
                    # Title
                    h3_a = item.xpath('.//h3/a')
                    title = ""
                    href = ""
                    if h3_a:
                        title = h3_a[0].xpath('string()').strip()
                        href = h3_a[0].get('href', '')

                    # Snippet
                    snippet = ""
                    for s in ['.//span[contains(@class,"content-right")]', './/div[contains(@class,"c-abstract")]',
                              './/span[contains(@class,"c-color")]', './/div[contains(@class,"c-span")]']:
                        els = item.xpath(s)
                        if els:
                            snippet = els[0].xpath('string()').strip()
                            if len(snippet) > 20: break

                    if title:
                        print(f"    [{title[:60]}] {snippet[:80]}")
                break

    except Exception as e:
        print(f"  FAIL: {e}")

# Test
test_baidu_web("Python 最新版本")
test_baidu_web("今天天气")
test_baidu_web("machine learning tutorial")
