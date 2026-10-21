"""Run realistic, messy queries against a live endpoint before judging.
python scripts/smoke.py https://<your-space>.hf.space
Prints status, latency, narrative source (slm vs template) and any verification issues. Add your own queries freely."""
import sys
import time

import httpx

QUERIES = [
    "Where can I go for a jog tomorrow morning near Indiranagar?",
    "My dad has a heart condition - when is it okay for him to walk in the park near Salt Lake this week?",
    "Kids football (5-a-side) this Sunday within 10 km of Gachibowli?",
    "Best sunset spot for photos near Juhu this evening",
    "Planning an outdoor wedding reception Saturday evening in Navi Mumbai - what should I watch out for?",
    "is it ok to bike to work at 9 near Wakad",          # missing AM/PM, tests assumptions
    "good place to play tennis after work",              # missing location -> clarification
    "what's the weather like on Mars",                   # out of scope
]


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:7860").rstrip("/")
    with httpx.Client(timeout=240) as c:
        print("health:", c.get(base + "/health").json())
        for q in QUERIES:
            t = time.time()
            r = c.post(base + "/ask", json={"question": q})
            j = r.json()
            m = j.get("meta", {})
            print(f"\n[{j.get('status')}] {time.time() - t:5.1f}s narrative={m.get('narrative_source')} issues={m.get('verification_issues')}\n  Q: {q}\n  A: {(j.get('answer') or j.get('message', ''))[:240]}")


if __name__ == "__main__":
    main()
