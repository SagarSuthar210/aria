"""Agentic web search: Gemini decides what to search / read, then returns
a spoken answer + clickable result cards. Cards only contain URLs the agent
actually saw in search results or fetched pages (no hallucinated links)."""
import os, json, socket, ipaddress, concurrent.futures as cf
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from google import genai
from google.genai import types

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
REGION = os.getenv("SEARCH_REGION", "in-en")
MAX_STEPS = 7
UA = {"User-Agent": "Mozilla/5.0 (compatible; AriaBot/1.0)"}

_client = None
def client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client

S = types.Schema
T = types.Type
TOOLS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="search_web",
        description="Search the web. Returns titles, URLs and snippets. Call several times with different queries to refine.",
        parameters=S(type=T.OBJECT, properties={"query": S(type=T.STRING)}, required=["query"]),
    ),
    types.FunctionDeclaration(
        name="read_page",
        description="Open a URL from the search results and read its text to verify details (price, availability, hours, specs).",
        parameters=S(type=T.OBJECT, properties={"url": S(type=T.STRING)}, required=["url"]),
    ),
    types.FunctionDeclaration(
        name="final_answer",
        description="Deliver the final response. Always end with this.",
        parameters=S(type=T.OBJECT, properties={
            "speech": S(type=T.STRING, description="1-3 short, natural sentences to be spoken aloud. No markdown, no URLs."),
            "cards": S(type=T.ARRAY, description="0-6 best results, most relevant first. Empty for pure chit-chat.", items=S(
                type=T.OBJECT,
                properties={
                    "title": S(type=T.STRING),
                    "url": S(type=T.STRING, description="Exact URL taken from search_web/read_page output."),
                    "description": S(type=T.STRING, description="One or two lines on why this result fits."),
                    "badge": S(type=T.STRING, description="Optional short highlight, e.g. a price, rating or date."),
                },
                required=["title", "url", "description"],
            )),
        }, required=["speech", "cards"]),
    ),
])

SYSTEM = """You are Aria, a warm, quick voice assistant (think Alexa+) with live web access.
For anything about the real world (products, places, news, prices, how-tos, videos, events, people,
facts that may have changed) you MUST use search_web, and read_page when details matter. Refine your
search if the first results are weak. Prefer direct listing/product/article pages over homepages.
Finish with final_answer: a brief spoken reply plus cards linking to the best pages.
Rules: only use URLs you actually saw in tool results. Speech must be short, conversational and
free of markdown or URLs. The user may be speaking, so expect informal phrasing. For small talk or
questions needing no web, call final_answer directly with no cards.
User region hint: India (use local currency/sites when relevant) unless they say otherwise."""

# ---------- tools ----------
def _public(url):
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True
    except Exception:
        return False

def _norm(u): return u.split("#")[0].rstrip("/")

def search_web(query, seen):
    with DDGS() as d:
        rows = list(d.text(query, region=REGION, max_results=8))
    out = []
    for r in rows:
        url = r.get("href") or r.get("url")
        if not url: continue
        seen[_norm(url)] = {"title": r.get("title", ""), "image": None}
        out.append({"title": r.get("title"), "url": url, "snippet": (r.get("body") or "")[:300]})
    return {"results": out}

def _fetch(url):
    r = requests.get(url, headers=UA, timeout=8)
    soup = BeautifulSoup(r.text, "html.parser")
    og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
    img = urljoin(url, og["content"]) if og and og.get("content") else None
    return soup, img

def read_page(url, seen):
    if not _public(url): return {"error": "URL not allowed"}
    try:
        soup, img = _fetch(url)
    except Exception as e:
        return {"error": f"fetch failed: {type(e).__name__}"}
    if _norm(url) in seen: seen[_norm(url)]["image"] = img
    for t in soup(["script", "style", "nav", "footer", "noscript", "svg"]): t.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    return {"url": url, "text": text[:4500]}

def _og_image(url):
    try:
        if not _public(url): return None
        return _fetch(url)[1]
    except Exception:
        return None

def _finalize(args, seen):
    cards = []
    for c in (args.get("cards") or [])[:6]:
        key = _norm(c.get("url", ""))
        if key not in seen: continue  # drop hallucinated links
        cards.append({**{k: c.get(k, "") for k in ("title", "url", "description", "badge")},
                      "image": seen[key]["image"]})
    need = [c for c in cards if not c["image"]]
    if need:
        with cf.ThreadPoolExecutor(6) as ex:
            for c, img in zip(need, ex.map(lambda c: _og_image(c["url"]), need)):
                c["image"] = img
    return {"speech": args.get("speech", ""), "cards": cards}

# ---------- agent loop (generator of UI events) ----------
def run_agent(message, history):
    contents = [types.Content(role="user" if h["role"] == "user" else "model",
                              parts=[types.Part(text=h["text"])]) for h in history[-10:]]
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))
    seen = {}
    yield {"type": "status", "text": "Thinking"}

    for step in range(MAX_STEPS):
        last = step == MAX_STEPS - 1
        cfg = types.GenerateContentConfig(
            system_instruction=SYSTEM, tools=[TOOLS],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(
                mode="ANY", allowed_function_names=["final_answer"] if last else None)),
        )
        resp = client().models.generate_content(model=MODEL, contents=contents, config=cfg)
        cand = resp.candidates[0].content
        calls = [p.function_call for p in cand.parts if p.function_call]
        if not calls:
            yield {"type": "result", "speech": resp.text or "Sorry, I got nothing.", "cards": []}
            return
        contents.append(cand)

        responses = []
        for fc in calls:
            a = dict(fc.args or {})
            if fc.name == "final_answer":
                yield {"type": "result", **_finalize(a, seen)}
                return
            if fc.name == "search_web":
                yield {"type": "status", "text": f"Searching “{a.get('query','')}”"}
                try: res = search_web(a.get("query", ""), seen)
                except Exception as e: res = {"error": f"search failed: {e}"}
            elif fc.name == "read_page":
                host = urlparse(a.get("url", "")).hostname or "page"
                yield {"type": "status", "text": f"Reading {host.removeprefix('www.')}"}
                res = read_page(a.get("url", ""), seen)
            else:
                res = {"error": "unknown tool"}
            responses.append(types.Part.from_function_response(name=fc.name, response=res))
        contents.append(types.Content(role="user", parts=responses))

    yield {"type": "result", "speech": "I couldn't finish that one. Try rephrasing?", "cards": []}
