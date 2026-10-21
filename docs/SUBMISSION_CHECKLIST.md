# Submission checklist (deadline: 24 Oct, 11:59 PM IST)

1. **Pick the model repo name**, `huggingface-cli login`, then
   `python scripts/publish_model.py --base Qwen/Qwen2.5-1.5B-Instruct --repo <you>/geoai-outdoor-slm`
   (add `--path ./geoai-slm-merged --fine-tuned` if you ran `training/`). Confirm the page is **public**, shows the licence and loads with `from_pretrained`.
2. **Deploy the API**: create a Hugging Face Space (SDK: Docker), push this repo, set the secret/variable `CONTACT_EMAIL`
   and build arg/ENV `SLM_MODEL_ID=<you>/geoai-outdoor-slm`. Free CPU Spaces are slow and sleep; consider a small always-on VM
   or at least hit `/health` before judging. Pre-warm: ask one question after each restart.
3. **Test live**: `python scripts/smoke.py https://<your-host>`. Check `narrative_source` is `slm` for most answers; if it is mostly `template`, read `verification_issues` and tune the prompt or use the GGUF backend.
4. **Fill placeholders** in `README.md` (endpoint URL, HF URL, team name) and in the deck.
5. **Push the code** to a public repo, submit the Google Form (link pending in the rulebook).
6. **Before judging**: no hard-coded answers anywhere (none in this repo), keep the endpoint up for the whole window, rehearse one live demo question per activity type.
