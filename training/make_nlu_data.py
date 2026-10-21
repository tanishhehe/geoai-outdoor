"""Synthetic instruction data for the ONE task worth fine-tuning: question -> {"activity","location","radius_km"} JSON.

Places and phrasings deliberately exclude the localities in the hackathon's sample questions, so a held-out
check on those samples is a real generalisation test (and nothing is hard-coded).
usage: python training/make_nlu_data.py --n 3000 --out training/nlu_train.jsonl
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.nlu import SLM_PROMPT          # noqa: E402  (train on exactly the prompt used at inference)
from app.activities import ACTIVITIES   # noqa: E402

PLACES = ["Indiranagar", "Salt Lake", "Adyar", "Sector 62 Noida", "Jubilee Hills", "Viman Nagar", "Banjara Hills", "Gachibowli",
          "Anna Nagar", "Hauz Khas", "Vastrapur", "Baner", "Kothrud", "Dwarka", "Navi Mumbai", "Koramangala", "Aundh", "Thane",
          "Malad", "Juhu", "Electronic City", "Mylapore", "New Town Kolkata", "Gomti Nagar", "Sarjapur Road", "Wakad", "Mulund"]
WHEN = ["tomorrow morning", "this evening", "on Sunday", "this weekend", "tonight", "after work", "in the next two days", "at 6 am", "on Friday afternoon", ""]
PHR = {
    "running": ["go for a run", "jog", "run a 5k", "do my morning run"], "cycling": ["cycle", "go for a bike ride", "ride my bicycle"],
    "golf": ["play golf", "get a round of golf in"], "cricket": ["play cricket", "have a cricket practice", "organise a gully cricket match"],
    "football": ["play football", "book a five-a-side game", "play soccer with friends"], "tennis": ["play tennis", "have a tennis session"],
    "hiking": ["go hiking", "do a nature walk", "trek"], "picnic": ["have a picnic", "plan a park outing with the family"],
    "event": ["host an outdoor birthday party", "hold an outdoor wedding reception", "run a small outdoor fair"],
    "photography": ["do a photoshoot", "take sunset photos", "shoot landscapes"], "walking": ["go for a walk", "take an evening stroll"],
    "badminton": ["play badminton", "set up an outdoor badminton game"], "basketball": ["play basketball", "shoot some hoops"],
    "swimming": ["go for a swim", "swim some laps outdoors"], "yoga": ["do outdoor yoga", "have an outdoor workout"],
    "camping": ["go camping", "pitch a tent for the night"], "stargazing": ["go stargazing", "see the milky way"],
    "birdwatching": ["go birdwatching", "do some birding"]}
TEMPL = ["Where can I {a} {w} near {p}?", "Best place to {a} {w} around {p}?", "I want to {a} {w} within {r} km of {p}. Any suggestions?",
         "{p}: good spot to {a} {w}?", "when and where should I {a} near {p} {w}", "Is there somewhere near {p} to {a} {w}?"]
NO_LOC = ["Where is a good place to {a} {w}?", "Best time to {a} {w}?", "I'd like to {a} {w}, ideas?"]
NONE_Q = ["What is the capital of Australia?", "Write me a poem about the monsoon", "How do I fix a flat tyre on my car?",
          "Explain how photosynthesis works", "Who won the cricket world cup in 2011?", "Translate 'good morning' into Tamil"]


def ex(q, act, loc, rad):
    target = json.dumps({"activity": act, "location": loc, "radius_km": rad}, ensure_ascii=False)
    return {"messages": [{"role": "user", "content": SLM_PROMPT.format(acts=list(ACTIVITIES), q=q)},
                         {"role": "assistant", "content": target}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--out", default="training/nlu_train.jsonl")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    random.seed(a.seed)
    rows = []
    for _ in range(a.n):
        k = random.random()
        act = random.choice(list(PHR))
        w, p = random.choice(WHEN), random.choice(PLACES)
        r = random.choice([None, None, 5, 10, 15, 20, 30])
        verb = random.choice(PHR[act])
        if k < .08:
            rows.append(ex(random.choice(NONE_Q), "none", None, None))
        elif k < .22:
            rows.append(ex(random.choice(NO_LOC).format(a=verb, w=w).replace("  ", " ").strip(), act, None, None))
        else:
            t = random.choice(TEMPL)
            if "{r}" in t and r is None:
                r = random.choice([10, 15, 25])
            rows.append(ex(t.format(a=verb, w=w, p=p, r=r).replace("  ", " ").strip(), act, p, r if "{r}" in t else None))
    Path(a.out).write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")
    print(f"wrote {len(rows)} examples to {a.out}")


if __name__ == "__main__":
    main()
