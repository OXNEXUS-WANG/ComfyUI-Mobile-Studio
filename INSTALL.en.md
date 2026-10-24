# CometInk 彗墨 — English installation & usage guide

CometInk is a local, mobile-first control room for ComfyUI on Windows. This guide covers installation, first launch, phone access, generation, the gallery, the admin console, LoRA training, the 3D star map, and common problems.

> The application UI is fully bilingual. The **installer UI is in Chinese**; the label map below lets you complete it without reading Chinese.

---

## 1. Requirements

- Windows 10 or 11, 64-bit
- NVIDIA GPU with **8GB VRAM or more** recommended (RTX 50 series requires a CUDA 12.8+ build)
- 16GB RAM recommended
- At least 20GB free disk space for the default model pack
- Internet access during installation
- A phone and the PC on the same Windows mobile hotspot for phone access

The installer can download ComfyUI and the default models. If you already have ComfyUI, you can point the installer at it.

---

## 2. Install

1. Download `CometInk-v1.3.15-Share.zip` from **Releases** and extract it to a normal folder. Do not run it from inside the ZIP.
2. Run **`install.bat`** (English entry point). `安装.bat` is the same installer under its Chinese name.
3. Choose the install directory. The default is:
   ```text
   D:\CometInk
   ```
4. Read the disclaimer, tick the acceptance checkbox, and continue.
5. Set an administrator password (at least 8 characters). Write it down.
6. Choose a model pack:
   - Press **Enter**: Anima 2B + upscale model (recommended, about 6GB)
   - Type **all**: all optional models (about 66GB)
   - Type **n**: skip models for now; run `模型下载.bat` later
7. Wait for the installer to finish. Do not close the window.

### Chinese installer label map

| Chinese prompt | Meaning |
|---|---|
| `安装目录` | Install directory |
| `设置管理员密码` | Set administrator password |
| `再输一次` | Repeat the password |
| `选择模型包` | Choose model pack |
| `直接回车` | Press Enter for the default |
| `输入 all` | Type `all` for every model |
| `输入 n` | Type `n` to skip model download |
| `[Y/n]` | Yes / no; Enter usually means yes |
| `按回车继续` | Press Enter to continue |

### Unattended install (no Chinese prompts)

Run PowerShell **as Administrator** in the extracted folder:

```powershell
$env:MGS_ADMIN_PASSWORD = "ChangeMe123!"
powershell -ExecutionPolicy Bypass -File installer\install.ps1 `
  -Yes -AcceptDisclaimer -NoDialog
```

Useful switches:

- `-SkipModels` — do not download models (use when models already exist)
- `-NoTranslate` — skip the Chinese-to-English translation pack
- `-NoShortcut` — do not create the desktop shortcut
- `-ComfyUIDir "D:\CometInk"` — reuse an existing ComfyUI
- `-InstallDir "D:\CometInk"` — choose the install directory

The installer log is still in Chinese, but it runs without questions when `-Yes` and `-AcceptDisclaimer` are supplied.

---

## 3. Start and sign in

1. Launch **CometInk Studio** from the desktop shortcut created by the installer.
2. Open:
   ```text
   https://127.0.0.1:8800/
   ```
3. Sign in with:
   - Account: `admin`
   - Password: the password you set during installation

The first visit uses a self-signed HTTPS certificate. The browser will warn you; choose **Advanced → Proceed**.

Switch the UI language with the button in the top-right corner (`EN` / `中文`).

---

## 4. Phone access

1. On Windows: **Settings → Network & Internet → Mobile hotspot → On**.
2. Connect the phone to that hotspot.
3. Open this address on the phone:
   ```text
   https://192.168.137.1:8800
   ```
4. Accept the certificate warning once.
5. Optional: use the browser menu → **Add to Home screen** to install it as a PWA.

The service listens only on `127.0.0.1` and `192.168.137.1`. It is not reachable from the public internet.

If the phone cannot connect:

- Make sure the phone is on the **PC hotspot**, not campus Wi-Fi or the home router.
- Use `https://`, not `http://`.
- Keep the `:8800` port.
- If the installer created `修复手机访问.bat`, run it as Administrator to add the firewall rule.

---

## 5. Generate an image

1. Open the **Generate** tab.
2. Choose a mode:
   - **Text to Image** — prompt only
   - **Image to Image** — upload a reference image and adjust denoise
   - **Text to Video** — short Wan video (480p, 1–3 seconds)
   - **Image to Video** — animate a reference image
3. Write the prompt. English works directly. Chinese is translated automatically when the Argos translation pack is installed.
4. Choose aspect ratio and base model. For anime, start with **Anima 2B**.
5. Choose a style if you want one.
6. Click **Generate**.

The first generation loads the model and is slower. Later generations reuse the loaded model.

Results appear on the right and are saved to the gallery. Use **View translation** to inspect the English prompt actually sent to the model.

---

## 6. Gallery

- Images are isolated by account and stored under the checkpoint name.
- Filter by **All / Favourite / Anime / Photoreal**.
- Search prompt keywords.
- Select multiple images to download a ZIP.
- Open an image to upscale, view it larger, or send it back to generation.
- Admin accounts can filter the gallery by user.

---

## 7. Admin console

The **Admin** tab is only visible to administrators. It includes:

- **Overview** — accounts, images, storage, traffic, GPU seconds, jobs
- **Accounts** — create normal accounts and 24-hour guests; enable, disable, delete, or batch-edit
- **Limits & features** — daily images, gallery size, storage, upload size, pixels, steps, images per run, concurrent jobs, traffic, GPU seconds, training limits, and 14 feature switches
- **Queue** — pause new jobs, maximum wait, maintenance windows, per-account priority
- **Workers** — approve LAN worker nodes and build worker bundles
- **Models** — upload, import from a server path, and delete to a seven-day recycle bin
- **Training** — install the trainer, approve requests, set windows and resource limits
- **Logs** — activity and security logs with search

Normal accounts never see the Admin tab and cannot call admin APIs.

---

## 8. LoRA training (optional)

1. Sign in as administrator.
2. Open the **Train** tab.
3. If the trainer is not installed, click **Install trainer**. The first install downloads kohya `sd-scripts` and a minimal dependency set into an isolated `trainer\` folder.
4. Create a training project:
   - Upload 5–100 images, or import them from your gallery
   - Set a trigger word and captions
   - Choose Anima 2B (recommended) or SDXL (experimental)
   - Set steps, resolution, and other parameters
5. Submit for approval.
6. An administrator approves the request. Training waits for the configured window and enough free VRAM.
7. When finished, the LoRA is published as private by default. The owner or an administrator can share it.

While training runs, local generation yields the GPU; LAN workers can still take jobs.

---

## 9. 3D API star map

Open it from **More ▾ → Open 3D API star map** (Chinese UI: **更多 ▾ → 打开 3D 接口星图**).

- Drag to rotate; wheel or pinch to zoom.
- Click a planet for details; double-click to open the related feature.
- Use **Flow** to show the 16-step main chain and B1–B5 branches.
- Press `P` for layout mode to drag and save planet positions.
- Press `B` to toggle the black-hole background.
- The in-map generation deck can submit jobs without leaving the star map.

---

## 10. Models and maintenance

- Run `模型下载.bat` to download or resume models. It is safe to run repeatedly.
- The web UI can also upload models or import them from a server path.
- Deleted models go to a recycle bin for seven days.
- `备份数据.bat` creates a backup; `恢复数据.bat` restores one.
- `打包到U盘.bat` bundles the app and models for offline migration.
- `运行测试.bat` runs the local test suite (developer use).

---

## 11. Common problems

**No base model in the Generate tab**

Run `模型下载.bat`, or import a model through the admin model manager. After a manual import, refresh the page.

**ComfyUI does not start**

- Check the NVIDIA driver and the CUDA 12.8+ build.
- Read the ComfyUI console window for the first error.
- Remove recently installed custom nodes and retry.

**Phone cannot open the page**

- Confirm the hotspot is on and the phone is connected to it.
- Use `https://192.168.137.1:8800`.
- Run the firewall repair script as Administrator.

**Certificate warning**

Expected with the self-signed certificate. Choose **Advanced → Proceed**. To regenerate the certificate for a new LAN IP, run the security setup script and choose the certificate option.

**Generation is slow**

- The first run loads the model.
- Lower resolution, steps, or batch size.
- Close other GPU-heavy applications.
- Check the system-load panel in the star map.

**English UI still shows some Chinese**

Prompt text, image captions, user display names, and plugin pack names are user content and are intentionally not translated. UI labels switch with the `EN` / `中文` button.

---

## 12. Security and license

- Designed for **LAN / Windows hotspot use only**.
- The service binds only `127.0.0.1` and `192.168.137.1`; never expose 8800/8188 to the public internet.
- Do not use port forwarding, tunnels, reverse proxies, VPNs, or public IPv6.
- The Share edition uses the **PolyForm Noncommercial License 1.0.0**. Commercial use requires a separate commercial licence.
- See `DISCLAIMER.md`, `LICENSE`, and `COMMERCIAL_LICENSE.md`.

---

Full bilingual showcase: **[GITHUB_INTRO.md](GITHUB_INTRO.md)**  
Chinese manual: **[MANUAL.md](MANUAL.md)**

---

## Contact

Questions, installation help, or collaboration: **gong390509996@163.com**
