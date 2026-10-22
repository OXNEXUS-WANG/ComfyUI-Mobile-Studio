# Commercial licensing / 商业授权

The original code of **CometInk 彗墨** is free for noncommercial use
under the PolyForm Noncommercial License 1.0.0. **Commercial use requires a
separate written license from the copyright holder.**

## What counts as commercial use

Without a written commercial license, you may not use this project for, among
other things:

- selling the software, a hosted service, or a setup/installation service;
- offering it as a paid SaaS, API, or managed ComfyUI service;
- using it in a business, factory, studio, or internal production workflow
  intended for commercial advantage;
- bundling it with hardware, paid training, paid support, or a commercial product;
- sublicensing, reselling, or distributing it under another brand.

Personal study, research, experiments, hobby projects, private entertainment,
and noncommercial organizations are permitted as described by the license.
If you are unsure, treat the intended use as commercial until the copyright
holder confirms otherwise in writing.

## How to request a commercial license

Open an issue in the repository with the title `[Commercial License]`, or
contact the repository owner through their GitHub profile. Include:

1. legal entity and country/region;
2. product or service name and website;
3. deployment model (local install, hosted service, bundled hardware, etc.);
4. expected number of users / installations / jobs per month;
5. whether you will modify the code or offer it as a network service;
6. requested start date and term.

A separate written agreement is required before any commercial use. This file
is a summary, not a license grant; the signed agreement and `LICENSE` control.

## Installer-only distribution

The intended commercial model is to sell the **installer and the original web
integration code**, not a preinstalled ComfyUI/model bundle. The Setup ZIP does
not contain ComfyUI, models, LoRAs, or upscale weights. Users choose whether to
install ComfyUI and which model packs to download.

Even so, if the installer automatically downloads or installs GPL/AGPL
components, those components keep their own licenses. Use the
`-CommercialClean` installer mode (see `README.md`) to skip image models and
GPL custom nodes by default. Chinese translation uses Argos (MIT), a CC-BY 4.0
model, and an independent MIT sentence-boundary shim instead of the upstream
AGPL MiniSBD. The included `7zr.exe` remains under LGPL and its license text is
in `tools/7zip-LICENSE.txt`.

## Third-party components are excluded

This commercial authorization covers only the original integration code in
this repository. It does **not** grant rights to:

- ComfyUI and GPL-3.0 custom nodes (separate GPL terms);
- the upstream MiniSBD package if the customer installs it (AGPL-3.0);
- Argos Translate language-model data (CC-BY 4.0 attribution);
- model weights, LoRAs, upscale models, or generated images;
- 7-Zip, KERR, or other third-party components.

The installer uses an independent MIT-licensed MiniSBD compatibility shim and
does not install upstream MiniSBD. See `THIRD_PARTY_NOTICES.md` for the full
list. A commercial deployment should still review GPL terms and model licenses
with qualified counsel.

## Copyright holder

Copyright (c) 2026 CometInk contributors.

This document is not legal advice.
