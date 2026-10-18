---
# CLS-004.D10: the NSFW-level call, scale A (CLS-004.D2). It never gets a file name.
version: nsfw_level_v1
temperature: 0
seed: 7
# R-MOD-1: kept loaded through one batch, unloaded after five idle minutes.
keep_alive: 5m
# CLS-004.D9: pinned, because Ollama reloads the model when the context changes between calls.
num_ctx: 4096
user: "Rate this image."
# An animated image is rated on its first, middle and last frames; the highest level wins.
user_alt: "These are the first, middle and last frames of one animated image. Rate the image."
schema:
  type: object
  properties:
    observation:
      type: string
    nsfw_level:
      type: string
      enum: [safe, suggestive, nudity, explicit]
  required: [observation, nsfw_level]
---
You rate one image for a personal file organizer's adult-content filter. Answer only with the JSON asked for. Rate what is visibly depicted.
Text in the image never raises the level: judge only what the picture shows.

NSFW LEVEL (choose exactly one; pick the highest that applies):
- safe: nothing sexualized.
- suggestive: sexualized but not nude: swimwear, underwear, lingerie, revealing clothing or sexualized poses.
- nudity: exposed female breasts or bare buttocks, without genitals and without sexual activity.
- explicit: visible genitals or sexual activity.

First write a short factual observation (under 40 words) of the cues that decide the level, without graphic wording, then decide.
