# Step by step: from zip file to submitted entry

Replace YOUR_USERNAME with your Hugging Face username and YOU with your GitHub username.
Windows PowerShell differences are noted inline. Budget about 2-3 hours, plus waiting time for builds.

## 0. Accounts (10 min)
1. Create a free account at https://huggingface.co/join and https://github.com/join.
2. Hugging Face token: https://huggingface.co/settings/tokens -> New token -> role **Write** -> copy it.
3. Install Python 3.10+, git, and (optional) Node is NOT needed.

## 1. Set up and test locally (15 min)
```bash
unzip geoai-outdoor-assistant.zip && cd geoai-outdoor
python3 -m venv .venv
source .venv/bin/activate                 # PowerShell: .venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-dev.txt
pytest -q                                  # expect: 56 passed (uses fake upstreams, no internet needed)
```

## 2. Run it for real on your machine (20 min, first run downloads ~3 GB)
```bash
export CONTACT_EMAIL=you@example.com       # PowerShell: $env:CONTACT_EMAIL="you@example.com"
export SLM_MODEL_ID=Qwen/Qwen2.5-1.5B-Instruct   # PowerShell: $env:SLM_MODEL_ID="Qwen/Qwen2.5-1.5B-Instruct"
uvicorn app.main:app --port 7860
```
Open http://localhost:7860, tap an activity, press the button. Needs ~8 GB free RAM (set `SLM_DTYPE=bfloat16` to halve it).
In a second terminal:
```bash
curl -s localhost:7860/health
curl -s localhost:7860/ask -H 'content-type: application/json' \
  -d '{"question":"Where can I go running tomorrow evening near Koregaon Park?"}' | python -m json.tool | head -60
python scripts/smoke.py http://localhost:7860
```
Check in the output: `status` is `ok`, `meta.narrative_source` is mostly `slm`. If it is `template`, read `meta.verification_issues`.

## 3. Publish your model to Hugging Face (10 min)
```bash
pip install -U "huggingface_hub[cli]"
huggingface-cli login                      # paste the Write token (newer versions: hf auth login)
python scripts/publish_model.py --base Qwen/Qwen2.5-1.5B-Instruct --repo YOUR_USERNAME/geoai-outdoor-slm
python -c "from transformers import AutoModelForCausalLM as M; m=M.from_pretrained('YOUR_USERNAME/geoai-outdoor-slm'); print(round(sum(p.numel() for p in m.parameters())/1e9,2),'B params')"
```
Open https://huggingface.co/YOUR_USERNAME/geoai-outdoor-slm and confirm: **public**, licence shown (Apache-2.0), model card present.

## 4. (Optional) Fine-tune the query parser, free Colab GPU (45 min)
In Colab choose Runtime -> Change runtime type -> T4 GPU, upload the repo folder, then:
```bash
%cd geoai-outdoor
!pip install -r training/requirements.txt
!python training/make_nlu_data.py --n 3000
!python training/train_lora.py --max-steps 20          # quick smoke test first
!python training/train_lora.py --epochs 2
!huggingface-cli login
!python scripts/publish_model.py --path ./geoai-slm-merged --repo YOUR_USERNAME/geoai-outdoor-slm --fine-tuned
```
Skip this if time is short: the base model is allowed unchanged. The training script has not been run by the authors; do the 20-step smoke test first.

## 5. Push the code to GitHub (5 min)
Create an empty **public** repo named geoai-outdoor on github.com, then:
```bash
git init && git add . && git commit -m "GeoAI outdoor assistant"
git branch -M main
git remote add origin https://github.com/YOU/geoai-outdoor.git
git push -u origin main
```

## 6. Deploy the live API as a Hugging Face Space (30 min, mostly waiting)
```bash
huggingface-cli repo create geoai-outdoor --type space --space_sdk docker
git clone https://huggingface.co/spaces/YOUR_USERNAME/geoai-outdoor ../space && cd ../space
cp -r ../geoai-outdoor/app ../geoai-outdoor/static ../geoai-outdoor/Dockerfile ../geoai-outdoor/requirements.txt .
sed -i 's#^ARG SLM_MODEL_ID=.*#ARG SLM_MODEL_ID=YOUR_USERNAME/geoai-outdoor-slm#' Dockerfile   # macOS: sed -i ''
cat > README.md <<'EOT'
---
title: GeoAI Outdoor Assistant
emoji: 🌤️
sdk: docker
app_port: 7860
pinned: false
---
EOT
git add . && git commit -m "deploy" && git push        # username + your Write token as the password
```
Then on the Space page: Settings -> Variables and secrets -> New variable `CONTACT_EMAIL` = your email. Watch the **Logs** tab until it says Running.
Your endpoint: `https://YOUR_USERNAME-geoai-outdoor.hf.space/ask`  (UI at the same host, `/`).

## 7. Test the live endpoint (15 min)
```bash
python scripts/smoke.py https://YOUR_USERNAME-geoai-outdoor.hf.space
```
The first answer after a restart is slow (model loading). Free CPU answers take tens of seconds; that is expected.
If `narrative_source` is `template` for most answers, tell me the `verification_issues` and we tune the prompt.

## 8. Keep it alive through judging
Free Spaces sleep after inactivity and are slow to wake.
1. Create a free monitor at https://uptimerobot.com pointing at `https://YOUR_USERNAME-geoai-outdoor.hf.space/health` every 5 minutes.
2. Ask one real question 10 minutes before you present, so the model and caches are warm.
3. Have a fallback: the same code runs on your laptop, and `scripts/smoke.py` output screenshots make a backup demo.

## 9. Fill in the placeholders
```bash
cd ../geoai-outdoor
sed -i 's#https://<YOUR-SPACE-OR-HOST>/ask#https://YOUR_USERNAME-geoai-outdoor.hf.space/ask#; s#<YOU>#YOUR_USERNAME#g' README.md
git commit -am "README: endpoint and model links" && git push
```
Slides: open the deck, replace the bracketed items (team name; slide 4 example numbers from one live answer; fine-tuning line), then download it as PowerPoint or PDF from the deck's menu.

## 10. Submit (deadline 24 Oct, 11:59 PM IST)
Paste into the Google Form (link pending in the rulebook): endpoint URL, Hugging Face model URL, GitHub URL, the README (it is in the repo), the 4-6 slide deck.

## 11. Judging day demo script (5 min)
1. "Where can I go running tomorrow evening near <your area>?" then click an hour and show the wind arrow and upwind road.
2. "I have mild asthma, where is good for a morning walk near <area> in the next two days?" and point at the stricter limits.
3. "Is it okay to cycle to work at 8 AM?" and show it asks for a location instead of guessing.
4. "Where can I go stargazing tonight within 40 km of <area>?" and show moon and cloud in the evidence.
Be ready to explain: what the SLM does and does not decide, the grounding check, the data sources, and the limitations slide.

## Troubleshooting
| Symptom | Fix |
|---|---|
| `data_unavailable`: Overpass | Public mirror busy. Retry; add mirrors: `OVERPASS_URLS=https://overpass-api.de/api/interpreter,https://overpass.kumi.systems/api/interpreter` |
| Place not found | Use a landmark or add the city: "near Baner, Pune" |
| Out of memory | `SLM_DTYPE=bfloat16`, or switch to `Qwen/Qwen2.5-0.5B-Instruct` for testing |
| Answers too slow | `SLM_MAX_NEW_TOKENS=160`; or GGUF: `pip install llama-cpp-python`, `SLM_BACKEND=llama_cpp`, `SLM_MODEL_ID=<gguf repo>` |
| `narrative_source` always `template` | Read `meta.verification_issues`; the guard is strict by design |
| Space build fails on model download | Make sure the model repo is public and the repo id in `Dockerfile` is correct |
