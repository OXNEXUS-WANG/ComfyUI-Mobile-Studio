/* LoRA 训练页：数据集、审核、进度、安装器。依赖 page.html 里的 uiT/esc/uiConfirm。 */
(function () {
  "use strict";

  var T = {
    draft: ["草稿", "Draft"], pending: ["待审核", "Pending"],
    approved: ["已批准", "Approved"], waiting_window: ["等待窗口", "Waiting window"],
    waiting_resources: ["等待 GPU", "Waiting GPU"],
    waiting_component: ["等待组件", "Waiting trainer"],
    queued: ["排队中", "Queued"], running: ["训练中", "Training"],
    saving: ["保存中", "Saving"], done: ["已完成", "Done"],
    error: ["失败", "Failed"], rejected: ["已拒绝", "Rejected"],
    cancelled: ["已取消", "Cancelled"]
  };
  var PRESET = {
    character: { dim: 16, alpha: 8, lr: 0.0001, repeats: 10, epochs: 10, res: 768 },
    style: { dim: 32, alpha: 16, lr: 0.00005, repeats: 10, epochs: 12, res: 768 },
    quick: { dim: 8, alpha: 4, lr: 0.0001, repeats: 5, epochs: 4, res: 512 }
  };
  var S = {
    data: null, admin: null, timer: 0, adminTimer: 0,
    detailId: "", detail: null, detailTick: 0,
    galleryTid: "", gallerySel: {}, galleryItems: [], adminAt: 0
  };

  function t(zh, en) { return uiT(zh, en); }
  function q(sel, root) { return (root || document).querySelector(sel); }
  function qa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function esc2(v) { return esc(String(v == null ? "" : v)); }
  function size(v) {
    v = Number(v || 0);
    if (v >= 1073741824) return (v / 1073741824).toFixed(1) + " GB";
    if (v >= 1048576) return (v / 1048576).toFixed(1) + " MB";
    if (v >= 1024) return (v / 1024).toFixed(0) + " KB";
    return v + " B";
  }
  function eta(sec) {
    sec = Number(sec || 0);
    if (!sec) return "—";
    if (sec < 60) return Math.round(sec) + t(" 秒", "s");
    if (sec < 3600) return Math.round(sec / 60) + t(" 分钟", " min");
    return (sec / 3600).toFixed(1) + t(" 小时", " h");
  }
  function statusText(s) {
    var v = T[s] || [s || "—", s || "—"];
    return t(v[0], v[1]);
  }
  function badge(s) {
    var cls = s === "done" ? "ok" : (s === "error" || s === "rejected" ? "bad" :
      (s === "running" || s === "saving" ? "warn" : ""));
    return '<span class="aw-badge ' + cls + '">' + esc2(statusText(s)) + "</span>";
  }
  function reasonText(s) {
    s = String(s || "");
    if (!s) return "";
    var map = {
      "用户取消": ["用户取消", "Cancelled by user"],
      "管理员取消": ["管理员取消", "Cancelled by admin"],
      "管理员停止": ["管理员停止", "Stopped by admin"],
      "等待当前出图任务结束": ["等待当前出图任务结束",
        "Waiting for the current generation job"],
      "还没到训练时间窗口": ["还没到训练时间窗口", "Waiting for the training window"],
      "训练组件未安装/自检失败": ["训练组件未安装/自检失败",
        "Trainer is not installed or failed its health check"],
      "训练已取消": ["训练已取消", "Training cancelled"]
    };
    if (map[s]) return t(map[s][0], map[s][1]);
    if (s.indexOf("系统内存不够") === 0) {
      return t("系统内存不够 ", "Not enough system RAM ") + s.replace(/^系统内存不够\s*/, "");
    }
    if (s.indexOf("显存不够") === 0) {
      return t("显存不够 ", "Not enough VRAM ") + s.replace(/^显存不够\s*/, "");
    }
    if (s.indexOf("当前机器硬件不满足") === 0) {
      return t(s, "This machine does not meet the minimum hardware for this training profile. Use Anima 2B or a stronger machine.");
    }
    if (s.indexOf("磁盘空间不够") === 0) {
      return t("磁盘空间不够 ", "Not enough disk space ") + s.replace(/^磁盘空间不够\s*/, "");
    }
    if (s.indexOf("训练进程异常退出") === 0) {
      return t("训练进程异常退出。", "Training process exited unexpectedly.");
    }
    return s;
  }
  function setStatus(id, text, bad) {
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = text || "";
    el.className = "pf-status" + (bad ? " err" : "");
  }
  async function api(url, opts) {
    opts = opts || {};
    opts.cache = "no-store";
    opts.credentials = "same-origin";
    var r = await fetch(url, opts);
    var j = {};
    try { j = await r.json(); } catch (e) {}
    if (!r.ok) {
      var err = new Error(j.error || (t("请求失败：", "Request failed: ") + r.status));
      err.payload = j;
      err.status = r.status;
      throw err;
    }
    return j;
  }
  function post(action, extra) {
    var body = Object.assign({ action: action }, extra || {});
    return api("/api/training", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  }
  function adminPost(action, extra) {
    var body = Object.assign({ action: action }, extra || {});
    return api("/api/admin/training", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  }

  function syncTab() {
    var tab = document.getElementById("trainTab");
    if (!tab) return;
    var me = window.__me || {};
    var can = me.role === "admin" || (me.limits && me.limits.features &&
      me.limits.features.train);
    tab.style.display = can ? "" : "none";
  }

  function summaryHtml() {
    var d = S.data || {};
    var tr = d.trainer || {};
    var sm = d.summary || {};
    var q = d.usage || {};
    var lim = d.limits || {};
    var cards = [];
    cards.push('<div class="ts' + (tr.ready ? "" : " bad") + '"><b>' +
      (tr.ready ? t("训练组件就绪", "Trainer ready") :
        (tr.installed ? t("组件需要自检", "Trainer needs check") :
          t("组件未安装", "Trainer not installed"))) + "</b>" +
      esc2(tr.version ? "sd-scripts " + tr.version : (tr.health_error || "")) + "</div>");
    cards.push('<div class="ts' + (sm.blocked ? " warn" : "") + '"><b>' +
      (sm.blocked ? t("GPU 训练中", "GPU training") : t("本机可出图", "GPU available")) +
      "</b>" + esc2(sm.blocked ? (sm.message || "") : t("训练开始后本机出图会排队", "Local generation queues during training")) + "</div>");
    cards.push('<div class="ts"><b>' + t("训练次数", "Training jobs") + "</b>" +
      esc2((q.train_jobs_today || 0) + " / " +
        (Number(lim.daily_training_jobs || 0) || "∞") + " " + t("今日", "today")) + "</div>");
    cards.push('<div class="ts"><b>' + t("训练时长", "Training time") + "</b>" +
      esc2(Math.round((q.train_seconds_month || 0) / 60) + " / " +
        (Number(lim.monthly_training_minutes || 0) || "∞") + " " + t("本月分钟", "min this month")) + "</div>");
    return '<div class="train-summary">' + cards.join("") + "</div>";
  }

  function projectCard(p) {
    var prog = p.progress || {};
    var pct = Math.max(0, Math.min(100, Number(prog.percent || 0)));
    var actions = '<button type="button" data-tr="open" data-tid="' + esc2(p.id) + '">' +
      t("详情", "Details") + "</button>";
    if (p.status === "draft" || p.status === "rejected" || p.status === "cancelled") {
      actions += '<button type="button" class="primary" data-tr="submit" data-tid="' +
        esc2(p.id) + '">' + t("提交审核", "Submit") + "</button>";
    }
    if (p.status === "pending" || p.status === "approved" ||
        p.status === "queued" || p.status === "running" ||
        p.status === "waiting_window" || p.status === "waiting_resources") {
      actions += '<button type="button" class="danger" data-tr="cancel" data-tid="' +
        esc2(p.id) + '">' + t("取消", "Cancel") + "</button>";
    }
    if (p.status === "done" && p.output && p.output.name) {
      actions += '<button type="button" class="primary" data-tr="use" data-tid="' +
        esc2(p.id) + '">' + t("去出图使用", "Use in generator") + "</button>";
    }
    if (["error", "cancelled", "rejected"].indexOf(p.status) >= 0) {
      actions += '<button type="button" data-tr="retry" data-tid="' +
        esc2(p.id) + '">' + t("重试", "Retry") + "</button>";
    }
    return '<div class="admin-worker"><div style="min-width:0">' +
      '<div class="aw-name"><b data-no-i18n>' + esc2(p.name) + "</b>" + badge(p.status) +
      (p.queue_position ? '<span class="aw-badge">' + t("排队 ", "Queue ") +
        p.queue_position + "</span>" : "") + "</div>" +
      '<div class="aw-meta">' + esc2((p.profile === "anima" ? "Anima 2B" : "SDXL") +
        " · " + (p.base_model || "")) + " · " + (p.dataset ? p.dataset.images : 0) +
      t(" 张 · ", " images · ") + (p.params ? p.params.max_steps : 0) +
      t(" 步 · ", " steps · ") + esc2(statusText(p.status)) + "</div>" +
      '<div class="train-progress"><i style="width:' + pct + '%"></i></div>' +
      '<div class="aw-meta">' + (prog.step || 0) + " / " + (prog.total_steps || 0) +
      " · " + t("损失 ", "loss ") + (prog.loss == null ? "—" : prog.loss) +
      " · " + t("预计 ", "ETA ") + eta(prog.eta_seconds) +
      (p.reason && p.status !== "done" ? " · " + esc2(reasonText(p.reason)) : "") + "</div>" +
      '</div><div class="model-actions">' + actions + "</div></div>";
  }

  function render() {
    syncTab();
    var d = S.data;
    if (!d) return;
    var sum = document.getElementById("trainSummary");
    if (sum) sum.innerHTML = summaryHtml();
    var box = document.getElementById("trainProjects");
    if (box) {
      box.innerHTML = (d.projects || []).length
        ? d.projects.map(projectCard).join("")
        : '<div class="admin-empty">' + t("还没有训练项目。点右上角「新建训练」。",
          "No training projects yet. Click New training.") + "</div>";
    }
    var adminBox = document.getElementById("trainAdminBox");
    if (adminBox) adminBox.style.display = d.admin ? "" : "none";
    if (d.admin) trainRenderAdmin();
    if (S.detailId) trainDetailTick();
  }

  async function loadTraining(show) {
    if (show) setStatus("trainStatus", t("正在读取训练数据…", "Loading training…"), false);
    try {
      S.data = await api("/api/training");
      if (!S.data.admin && !S.data.can_train) {
        var n = document.getElementById("trainNotice");
        if (n) n.textContent = t("管理员还没有开启你的 LoRA 训练功能。",
          "The administrator has not enabled LoRA training for you.");
      }
      render();
      if (S.data.admin && (!S.admin || Date.now() - S.adminAt > 10000)) {
        loadAdmin();
      }
      setStatus("trainStatus", "", false);
    } catch (e) {
      setStatus("trainStatus", t("读取失败：", "Load failed: ") + e.message, true);
    }
  }

  function trainStart() {
    if (S.timer) return;
    loadTraining(false);
    S.timer = setInterval(function () { loadTraining(false); }, 4000);
  }
  function trainStop() {
    if (S.timer) { clearInterval(S.timer); S.timer = 0; }
    if (S.adminTimer) { clearInterval(S.adminTimer); S.adminTimer = 0; }
  }

  /* ---------------- 新建 ---------------- */
  function profileData(key) {
    var list = (S.data && S.data.profiles) || [];
    return list.find(function (p) { return p.key === key; }) || null;
  }
  function profileFits(p) {
    var h = (S.data && S.data.hardware) || {};
    if (!p) return true;
    var v = Number(p.min_total_vram_mb || 0);
    var r = Number(p.min_total_ram_mb || 0);
    if (v && h.vram_total_mb && Number(h.vram_total_mb) < v) return false;
    if (r && h.ram_total_mb && Number(h.ram_total_mb) < r) return false;
    return true;
  }
  function fillModels() {
    var key = q("#tnProfile").value;
    var p = profileData(key);
    var sel = q("#tnModel");
    sel.innerHTML = "";
    ((p && p.models) || []).forEach(function (m) {
      var o = document.createElement("option");
      o.value = m.name; o.textContent = m.label || m.name;
      sel.appendChild(o);
    });
    if (!(p && p.models && p.models.length)) {
      var o = document.createElement("option");
      o.value = ""; o.textContent = t("这个底模不可用", "Model unavailable");
      sel.appendChild(o);
    }
    var note = q("#tnProfileNote");
    if (note) {
      var text = p ? t(p.note, p.note_en) : "";
      if (p && !profileFits(p)) {
        text += t(" 当前机器达不到这个训练类型的最低配置，提交后会被拒绝。",
          " This machine does not meet the minimum hardware, so submission will be rejected.");
      }
      note.textContent = text;
    }
    var save = q("#trainNewSave");
    if (save) save.disabled = !!(p && !profileFits(p));
  }
  function applyPreset() {
    var v = PRESET[q("#tnPreset").value] || PRESET.character;
    q("#tnDim").value = v.dim; q("#tnAlpha").value = v.alpha;
    q("#tnLr").value = v.lr; q("#tnRepeats").value = v.repeats;
    q("#tnEpochs").value = v.epochs; q("#tnResolution").value = String(v.res);
  }
  function openNew() {
    if (!S.data) { loadTraining(true); return; }
    if (!S.data.can_train) {
      setStatus("trainStatus", t("管理员还没有开启你的训练功能。",
        "Training is not enabled for your account."), true);
      return;
    }
    var sel = q("#tnProfile");
    sel.innerHTML = "";
    (S.data.profiles || []).forEach(function (p) {
      if (!p.ready) return;
      var o = document.createElement("option");
      o.value = p.key;
      var label = p.label || p.key;
      if (p.key === "anima" && !/推荐|recommended/i.test(label)) {
        label += t("（推荐）", " (recommended)");
      }
      o.textContent = label;
      sel.appendChild(o);
    });
    if (!sel.options.length) {
      setStatus("trainStatus", t("没有可用的训练底模，请确认模型文件。",
        "No available base model. Check model files."), true);
      return;
    }
    fillModels(); applyPreset();
    q("#tnName").value = ""; q("#tnTrigger").value = ""; q("#tnCaption").value = "";
    setStatus("trainNewStatus", "", false);
    q("#trainNewPop").classList.add("on");
  }
  async function createProject() {
    var name = q("#tnName").value.trim();
    if (!name) { setStatus("trainNewStatus", t("请填写训练名称。", "Please enter a name."), true); return; }
    var profile = q("#tnProfile").value;
    var base = q("#tnModel").value;
    if (!base) { setStatus("trainNewStatus", t("没有可用底模。", "No base model."), true); return; }
    var prof = profileData(profile);
    if (prof && !profileFits(prof)) {
      setStatus("trainNewStatus", t(
        "这台机器的显存或内存达不到该训练类型的最低要求，请改用 Anima 2B，或换更强的机器。",
        "This machine does not meet the minimum VRAM/RAM for this training type. Use Anima 2B or a stronger machine."), true);
      return;
    }
    var body = {
      name: name, profile: profile, base_model: base,
      trigger: q("#tnTrigger").value.trim(),
      caption_default: q("#tnCaption").value.trim(),
      params: {
        preset: q("#tnPreset").value,
        resolution: Number(q("#tnResolution").value),
        network_dim: Number(q("#tnDim").value),
        network_alpha: Number(q("#tnAlpha").value),
        learning_rate: Number(q("#tnLr").value),
        num_repeats: Number(q("#tnRepeats").value),
        epochs: Number(q("#tnEpochs").value),
        max_steps: Number(q("#tnSteps").value)
      }
    };
    try {
      setStatus("trainNewStatus", t("正在创建…", "Creating…"), false);
      var j = await post("create", body);
      q("#trainNewPop").classList.remove("on");
      await loadTraining(false);
      openDetail(j.project.id);
    } catch (e) {
      setStatus("trainNewStatus", e.message, true);
    }
  }

  /* ---------------- 详情 ---------------- */
  function openDetail(tid) {
    S.detailId = tid;
    S.detail = null;
    q("#trainDetailPop").classList.add("on");
    q("#tdBody").innerHTML = '<div class="empty">' + t("正在读取…", "Loading…") + "</div>";
    refreshDetail(true);
    if (S.detailTick) clearInterval(S.detailTick);
    S.detailTick = setInterval(function () { refreshDetail(false); }, 3000);
  }
  function closeDetail() {
    S.detailId = "";
    S.detail = null;
    if (S.detailTick) { clearInterval(S.detailTick); S.detailTick = 0; }
    q("#trainDetailPop").classList.remove("on");
  }
  async function refreshDetail(renderAll) {
    if (!S.detailId) return;
    try {
      var j = await api("/api/training/status?project_id=" + encodeURIComponent(S.detailId));
      S.detail = j.project;
      if (renderAll) renderDetail();
      else trainDetailTick();
    } catch (e) {
      if (renderAll) q("#tdBody").innerHTML = '<div class="pf-status err">' + esc2(e.message) + "</div>";
    }
  }
  function detailActions(p) {
    var out = "";
    if (p.status === "draft" || p.status === "rejected" || p.status === "cancelled") {
      out += '<button type="button" class="primary" data-td="submit">' + t("提交审核", "Submit") + "</button>";
      out += '<button type="button" data-td="gallery">' + t("从图库选择", "Pick from gallery") + "</button>";
      out += '<label class="chip" style="min-height:44px;display:inline-flex;align-items:center;cursor:pointer">' +
        t("上传图片", "Upload") + '<input id="tdUpload" type="file" accept="image/*" multiple style="display:none"></label>';
    }
    if (p.status === "pending" || p.status === "approved" || p.status === "queued" ||
        p.status === "running" || p.status === "saving" ||
        p.status === "waiting_window" || p.status === "waiting_resources") {
      out += '<button type="button" class="danger" data-td="cancel">' + t("取消训练", "Cancel") + "</button>";
    }
    if (p.status === "done" && p.output && p.output.name) {
      out += '<button type="button" class="primary" data-td="use">' + t("去出图使用", "Use in generator") + "</button>";
      out += '<button type="button" data-td="download">' + t("下载 LoRA", "Download LoRA") + "</button>";
    }
    if (["error", "cancelled", "rejected"].indexOf(p.status) >= 0) {
      out += '<button type="button" class="primary" data-td="retry">' + t("重试", "Retry") + "</button>";
    }
    if (["done", "cancelled", "error", "rejected", "draft"].indexOf(p.status) >= 0) {
      out += '<button type="button" class="danger" data-td="delete">' + t("删除记录", "Delete") + "</button>";
    }
    return '<div class="train-actions">' + out + "</div>";
  }
  function renderDetail() {
    var p = S.detail;
    if (!p) return;
    q("#tdTitle").textContent = p.name || t("训练详情", "Training details");
    q("#tdSub").textContent = (p.profile === "anima" ? "Anima 2B" : "SDXL") +
      " · " + (p.base_model || "") + " · " + statusText(p.status) +
      (p.dataset ? " · " + p.dataset.images + t(" 张图", " images") : "");
    var prog = p.progress || {};
    var pct = Math.max(0, Math.min(100, Number(prog.percent || 0)));
    var h = detailActions(p);
    h += '<div class="train-progress"><i style="width:' + pct + '%"></i></div>' +
      '<div class="aw-meta" id="tdProgress">' + (prog.step || 0) + " / " +
      (prog.total_steps || 0) + " · " + t("损失 ", "loss ") +
      (prog.loss == null ? "—" : prog.loss) + " · " + t("预计 ", "ETA ") +
      eta(prog.eta_seconds) + (p.reason ? " · " + esc2(reasonText(p.reason)) : "") + "</div>";
    if (p.status === "draft" || p.status === "rejected" || p.status === "cancelled") {
      h += '<div class="train-form"><label>' + t("触发词", "Trigger") +
        '<input id="tdTrigger" maxlength="60" value="' + esc2(p.trigger || "") + '"></label>' +
        '<label>' + t("默认描述", "Default caption") +
        '<input id="tdCaption" maxlength="500" value="' + esc2(p.caption_default || "") + '"></label></div>' +
        '<div class="train-actions"><button type="button" data-td="save">' + t("保存参数", "Save") + "</button></div>";
    }
    h += '<div class="train-thumb-grid" id="tdImages"></div>';
    var imgs = (p.images || []);
    var grid = "";
    imgs.forEach(function (im) {
      grid += '<div class="train-thumb"><img src="' + esc2(im.url) + '" alt="">' +
        '<button class="x" type="button" data-td="rmimg" data-iid="' + esc2(im.id) + '">×</button>' +
        '<input class="cap" data-no-i18n data-iid="' + esc2(im.id) + '" value="' +
        esc2(im.caption || "") + '" placeholder="' + t("这张图的 caption", "Caption") + '"></div>';
    });
    h += '<div class="aw-meta" id="tdImageCount">' + imgs.length + t(" 张 · 至少 5 张", " images · at least 5") + "</div>";
    h += '<pre class="train-log" id="tdLog" data-no-i18n></pre>';
    q("#tdBody").innerHTML = h;
    q("#tdImages").innerHTML = grid;
    var file = document.getElementById("tdUpload");
    if (file) file.onchange = function () { uploadFiles(this.files); this.value = ""; };
    qa("#tdImages .cap").forEach(function (el) {
      el.onchange = function () {
        post("set_caption", { project_id: S.detailId, image_id: el.dataset.iid,
          caption: el.value }).then(function () { refreshDetail(true); })
          .catch(function (e) { setStatus("trainStatus", e.message, true); });
      };
    });
    loadDetailLog();
  }
  function trainDetailTick() {
    if (!S.detailId || !S.detail) return;
    var p = S.detail;
    var prog = p.progress || {};
    var el = document.getElementById("tdProgress");
    if (el) {
      el.textContent = (prog.step || 0) + " / " + (prog.total_steps || 0) +
        " · " + t("损失 ", "loss ") + (prog.loss == null ? "—" : prog.loss) +
        " · " + t("预计 ", "ETA ") + eta(prog.eta_seconds) +
        (p.reason ? " · " + reasonText(p.reason) : "");
    }
    if (["running", "saving", "done", "error", "cancelled"].indexOf(p.status) >= 0) {
      loadDetailLog();
    }
    if (p.status === "done" && q("#tdBody").innerHTML.indexOf("data-td=\"download\"") < 0) {
      renderDetail();
    }
  }
  async function loadDetailLog() {
    if (!S.detailId) return;
    try {
      var j = await api("/api/training/log?project_id=" + encodeURIComponent(S.detailId));
      var el = document.getElementById("tdLog");
      if (el) {
        el.textContent = (j.text || "").slice(-12000);
        el.scrollTop = el.scrollHeight;
      }
    } catch (e) {}
  }
  async function saveDetail() {
    var p = S.detail;
    if (!p) return;
    try {
      await post("update", { project_id: p.id,
        trigger: (q("#tdTrigger") || {}).value || "",
        caption_default: (q("#tdCaption") || {}).value || "" });
      await refreshDetail(true);
      await loadTraining(false);
    } catch (e) { setStatus("trainStatus", e.message, true); }
  }
  async function uploadFiles(files) {
    if (!files || !files.length || !S.detailId) return;
    var list = Array.prototype.slice.call(files).slice(0, 30);
    var done = 0;
    for (var i = 0; i < list.length; i++) {
      var f = list[i];
      if (!f.type || f.type.indexOf("image/") !== 0) continue;
      if (f.size > 20 * 1048576) {
        setStatus("trainStatus", t("图片太大：", "Image too large: ") + f.name, true);
        continue;
      }
      try {
        setStatus("trainStatus", t("正在上传 ", "Uploading ") + (i + 1) + "/" + list.length, false);
        var st = await post("upload_start", { project_id: S.detailId,
          filename: f.name, size: f.size });
        var offset = 0;
        while (offset < f.size) {
          var chunk = f.slice(offset, Math.min(f.size, offset + st.chunk_size));
          var buf = await chunk.arrayBuffer();
          var r = await fetch("/api/training/upload_chunk?upload_id=" +
            encodeURIComponent(st.upload_id) + "&offset=" + offset, {
            method: "POST", credentials: "same-origin", body: buf,
            headers: { "Content-Type": "application/octet-stream" }
          });
          var j = await r.json().catch(function () { return {}; });
          if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
          offset = j.received || (offset + buf.byteLength);
        }
        await post("upload_finish", { project_id: S.detailId,
          upload_id: st.upload_id, caption: "" });
        done += 1;
      } catch (e) {
        setStatus("trainStatus", t("上传失败：", "Upload failed: ") + f.name + " · " + e.message, true);
      }
    }
    await refreshDetail(true);
    await loadTraining(false);
    if (done) setStatus("trainStatus", t("已加入 " + done + " 张图片。", "Added " + done + " images."), false);
  }

  /* ---------------- 图库选择 ---------------- */
  async function openGallery() {
    S.galleryTid = S.detailId;
    S.gallerySel = {};
    q("#trainGalleryPop").classList.add("on");
    q("#tgGrid").innerHTML = '<div class="empty">' + t("正在读取图库…", "Loading gallery…") + "</div>";
    setStatus("tgStatus", "", false);
    try {
      var j = await api("/api/gallery?offset=0&limit=120&kind=all&fav=0&user=&team=&q=");
      S.galleryItems = j.items || [];
      q("#tgGrid").innerHTML = S.galleryItems.length ? S.galleryItems.map(function (it) {
        return '<div class="tg" data-name="' + esc2(it.name) + '"><img loading="lazy" src="/thumb/' +
          encodeURIComponent(it.name) + '" alt=""></div>';
      }).join("") : '<div class="empty">' + t("图库还没有图片", "Gallery is empty") + "</div>";
    } catch (e) {
      q("#tgGrid").innerHTML = '<div class="pf-status err">' + esc2(e.message) + "</div>";
    }
  }
  async function addGallery() {
    var names = Object.keys(S.gallerySel);
    if (!names.length) { setStatus("tgStatus", t("先点选图片。", "Pick images first."), true); return; }
    try {
      setStatus("tgStatus", t("正在复制…", "Copying…"), false);
      var j = await post("add_gallery", { project_id: S.galleryTid, names: names });
      q("#trainGalleryPop").classList.remove("on");
      setStatus("trainStatus", t("已加入 " + (j.added || 0) + " 张。",
        "Added " + (j.added || 0) + " images."), !!(j.errors && j.errors.length));
      await refreshDetail(true);
      await loadTraining(false);
    } catch (e) { setStatus("tgStatus", e.message, true); }
  }

  /* ---------------- 管理端 ---------------- */
  async function loadAdmin() {
    if (!S.data || !S.data.admin) return;
    try {
      S.admin = await api("/api/admin/training");
      S.adminAt = Date.now();
      trainRenderAdmin();
    } catch (e) {}
  }
  function installCard() {
    var tr = (S.admin && S.admin.trainer) || (S.data && S.data.trainer) || {};
    var log = tr.log_tail || "";
    var h = '<div class="train-install"><div class="ti-head"><b>' +
      t("训练组件", "Trainer") + "</b>" +
      '<span class="aw-badge ' + (tr.ready ? "ok" : "warn") + '">' +
      (tr.ready ? t("就绪", "Ready") : (tr.installed ? t("需修复", "Needs repair") :
        t("未安装", "Not installed"))) + "</span>" +
      (tr.version ? "<span>" + esc2(tr.version) + "</span>" : "") +
      (tr.installing ? '<span class="spin"></span>' + t("安装中…", "Installing…") : "") +
      '<span style="margin-left:auto"></span>' +
      '<button class="reload" type="button" data-ta="install">' +
      (tr.installed ? t("修复 / 更新", "Repair / update") : t("安装训练组件", "Install trainer")) +
      "</button>" +
      (tr.installed ? '<button class="reload danger" type="button" data-ta="uninstall">' +
        t("卸载", "Uninstall") + "</button>" : "") + "</div>";
    if (tr.health_error) h += '<div class="aw-meta">' + esc2(tr.health_error) + "</div>";
    if (log) h += '<div class="ti-log" data-no-i18n>' + esc2(log) + "</div>";
    return h + "</div>";
  }
  function settingsCard() {
    var raw = ((S.admin && S.admin.settings && S.admin.settings.raw) ||
      (S.data && S.data.settings && S.data.settings.raw) || {});
    var w = raw.window || {};
    function checked(v) { return v ? " selected" : ""; }
    return '<div class="train-install"><div class="ti-head"><b>' +
      t("训练设置", "Training settings") + "</b></div>" +
      '<div class="train-settings">' +
      '<label>' + t("总开关", "Enabled") + '<select id="tsEnabled"><option value="1"' +
      checked(raw.enabled) + '>' + t("开启", "On") + '</option><option value="0"' +
      (!raw.enabled ? " selected" : "") + '>' + t("关闭", "Off") + "</option></select></label>" +
      '<label>' + t("需要审核", "Require approval") + '<select id="tsApproval"><option value="1"' +
      checked(raw.approval_required) + '>' + t("是", "Yes") + '</option><option value="0"' +
      (!raw.approval_required ? " selected" : "") + '>' + t("否", "No") + "</option></select></label>" +
      '<label>' + t("暂停队列", "Pause queue") + '<select id="tsPaused"><option value="0"' +
      (!raw.paused ? " selected" : "") + '>' + t("否", "No") + '</option><option value="1"' +
      (raw.paused ? " selected" : "") + '>' + t("是", "Yes") + "</option></select></label>" +
      '<label>' + t("训练窗口", "Window") + '<select id="tsWindow"><option value="0"' +
      (!w.enabled ? " selected" : "") + '>' + t("不限制", "Any time") + '</option><option value="1"' +
      (w.enabled ? " selected" : "") + '>' + t("只在指定时段", "Window only") + "</option></select></label>" +
      '<label>' + t("窗口开始", "Window start") + '<input id="tsWinStart" value="' +
      esc2(w.start || "01:00") + '"></label>' +
      '<label>' + t("窗口结束", "Window end") + '<input id="tsWinEnd" value="' +
      esc2(w.end || "07:00") + '"></label>' +
      '<label>' + t("最大步数", "Max steps") + '<input id="tsMaxSteps" type="number" value="' +
      (raw.max_steps || 3000) + '"></label>' +
      '<label>' + t("数据集张数", "Max images") + '<input id="tsMaxImages" type="number" value="' +
      (raw.max_dataset_images || 100) + '"></label>' +
      '<label>' + t("数据集 MB", "Max dataset MB") + '<input id="tsMaxMB" type="number" value="' +
      (raw.max_dataset_mb || 2048) + '"></label>' +
      '<label>' + t("Anima 空闲显存 MB", "Anima free VRAM MB") + '<input id="tsVramA" type="number" value="' +
      (raw.min_free_vram_mb_anima || 4200) + '"></label>' +
      '<label>' + t("SDXL 空闲显存 MB", "SDXL free VRAM MB") + '<input id="tsVramS" type="number" value="' +
      (raw.min_free_vram_mb_sdxl || 6000) + '"></label>' +
      '<label>' + t("保留检查点", "Keep checkpoints") + '<input id="tsKeep" type="number" value="' +
      (raw.keep_checkpoints || 2) + '"></label>' +
      '<label>' + t("允许 NoobAI v-pred", "Allow NoobAI v-pred") + '<select id="tsVpred"><option value="0"' +
      (!raw.allow_sdxl_vpred ? " selected" : "") + '>' + t("否（未验证）", "No (unverified)") + '</option><option value="1"' +
      (raw.allow_sdxl_vpred ? " selected" : "") + '>' + t("是", "Yes") + "</option></select></label>" +
      '</div><div class="train-actions"><button type="button" class="primary" data-ta="settings">' +
      t("保存设置", "Save settings") + "</button></div></div>";
  }
  function pendingCard(p) {
    var prog = p.progress || {};
    return '<div class="admin-worker"><div><div class="aw-name"><b data-no-i18n>' +
      esc2(p.name) + "</b>" + badge(p.status) + "</div>" +
      '<div class="aw-meta" data-no-i18n>' + esc2(p.user_name || p.username || p.user_id) +
      " · " + esc2(p.profile === "anima" ? "Anima 2B" : "SDXL") + " · " +
      (p.dataset ? p.dataset.images : 0) + t(" 张 · ", " images · ") +
      (p.params ? p.params.max_steps : 0) + t(" 步", " steps") + "</div></div>" +
      '<div class="model-actions"><button type="button" data-ta="approve" data-tid="' +
      esc2(p.id) + '">' + t("通过", "Approve") + "</button>" +
      '<button type="button" class="danger" data-ta="reject" data-tid="' +
      esc2(p.id) + '">' + t("拒绝", "Reject") + "</button>" +
      '<button type="button" data-ta="openadmin" data-tid="' + esc2(p.id) + '">' +
      t("详情", "Details") + "</button></div></div>";
  }
  function loraCard(x) {
    var meta = x.meta || {};
    var open = !!meta.public;
    var owned = !!(meta.owner_id || meta.project_id);
    var state = !owned ? '<span class="aw-badge">' + t("历史 / 共享", "Legacy / shared") + "</span>" :
      (open ? '<span class="aw-badge ok">' + t("共享", "Shared") + "</span>" :
        '<span class="aw-badge">' + t("私有", "Private") + "</span>");
    var actions = owned
      ? '<button type="button" data-ta="share" data-name="' + esc2(x.name) +
        '" data-public="' + (open ? "0" : "1") + '">' +
        (open ? t("取消共享", "Unshare") : t("共享给所有人", "Share with all")) + "</button>"
      : "";
    actions += '<button type="button" class="danger" data-ta="dellora" data-name="' +
      esc2(x.name) + '">' + t("删除", "Delete") + "</button>";
    return '<div class="admin-worker"><div><div class="aw-name"><b data-no-i18n>' +
      esc2(x.name) + "</b>" + state + "</div>" +
      '<div class="aw-meta" data-no-i18n>' + esc2((meta.display_name || "") + " · " +
        (meta.owner_id || "") + " · " + (x.family || "") + " · " + size(x.size)) + "</div></div>" +
      '<div class="model-actions">' + actions + "</div></div>";
  }
  function trainRenderAdmin() {
    var box = document.getElementById("trainAdminContent");
    if (!box || !S.admin) return;
    var h = installCard() + settingsCard();
    h += '<div class="admin-worker-head"><div><h3>' + t("待审核", "Pending approval") +
      "</h3><p>" + t("通过后才会进入 GPU 队列；可以拒绝并写明原因。",
        "Approved projects enter the GPU queue. You can reject with a reason.") + "</p></div></div>";
    h += '<div class="admin-models">' + ((S.admin.pending || []).length
      ? S.admin.pending.map(pendingCard).join("")
      : '<div class="admin-empty">' + t("没有待审核训练", "No pending training") + "</div>") + "</div>";
    h += '<div class="admin-worker-head"><div><h3>' + t("训练中的任务", "Active training") +
      '</h3></div></div><div class="admin-models">' +
      ((S.admin.projects || []).filter(function (p) {
        return ["running", "saving", "queued", "approved", "waiting_window",
          "waiting_resources", "waiting_component"].indexOf(p.status) >= 0;
      }).map(function (p) {
        return '<div class="admin-worker"><div><div class="aw-name"><b data-no-i18n>' +
          esc2(p.name) + "</b>" + badge(p.status) + "</div><div class=\"aw-meta\">" +
          esc2(reasonText(p.reason || "")) + "</div></div><div class=\"model-actions\">" +
          '<button type="button" data-ta="openadmin" data-tid="' + esc2(p.id) + '">' +
          t("详情", "Details") + "</button>" +
          '<button type="button" class="danger" data-ta="cancel" data-tid="' +
          esc2(p.id) + '">' + t("停止", "Stop") + "</button></div></div>";
      }).join("") || '<div class="admin-empty">' + t("没有排队/运行中的训练", "No active training") + "</div>") + "</div>";
    h += '<div class="admin-worker-head"><div><h3>' + t("训练出的 LoRA", "Trained LoRAs") +
      "</h3><p>" + t("默认只有训练者和管理员可见；共享后所有账号可用。",
        "Private by default; shared LoRAs are visible to all accounts.") + "</p></div></div>";
    h += '<div class="admin-models">' + ((S.admin.loras || []).length
      ? S.admin.loras.map(loraCard).join("")
      : '<div class="admin-empty">' + t("还没有训练出的 LoRA", "No trained LoRA yet") + "</div>") + "</div>";
    box.innerHTML = h;
  }
  async function saveSettings() {
    var settings = {
      enabled: q("#tsEnabled").value === "1",
      approval_required: q("#tsApproval").value === "1",
      paused: q("#tsPaused").value === "1",
      window: {
        enabled: q("#tsWindow").value === "1",
        start: q("#tsWinStart").value.trim(),
        end: q("#tsWinEnd").value.trim()
      },
      max_steps: Number(q("#tsMaxSteps").value),
      max_dataset_images: Number(q("#tsMaxImages").value),
      max_dataset_mb: Number(q("#tsMaxMB").value),
      min_free_vram_mb_anima: Number(q("#tsVramA").value),
      min_free_vram_mb_sdxl: Number(q("#tsVramS").value),
      keep_checkpoints: Number(q("#tsKeep").value),
      allow_sdxl_vpred: q("#tsVpred").value === "1"
    };
    try {
      await adminPost("settings", { settings: settings });
      setStatus("trainStatus", t("训练设置已保存。", "Training settings saved."), false);
      await loadAdmin();
      await loadTraining(false);
    } catch (e) { setStatus("trainStatus", e.message, true); }
  }
  async function approve(tid) {
    var ok = await uiConfirm({
      title: t("批准训练", "Approve training"),
      message: t("批准后会在 GPU 空闲时开始训练，可能占用显卡几十分钟到数小时。",
        "Training starts when the GPU is free and may occupy it for hours."),
      ack: t("我确认这会占用 GPU", "I understand this uses the GPU"),
      okText: t("批准", "Approve"), danger: true
    });
    if (!ok) return;
    try {
      await adminPost("approve", { project_id: tid, priority: 0, max_minutes: 240 });
      await loadAdmin(); await loadTraining(false);
    } catch (e) { setStatus("trainStatus", e.message, true); }
  }
  async function reject(tid) {
    var reason = window.prompt(t("拒绝原因（用户可见）", "Rejection reason (visible to user)"),
      t("不符合训练要求", "Does not meet the training requirements"));
    if (reason == null) return;
    try {
      await adminPost("reject", { project_id: tid, reason: reason });
      await loadAdmin(); await loadTraining(false);
    } catch (e) { setStatus("trainStatus", e.message, true); }
  }
  async function adminAction(action, el) {
    var tid = el.getAttribute("data-tid") || "";
    var name = el.getAttribute("data-name") || "";
    try {
      if (action === "settings") return saveSettings();
      if (action === "install") {
        await adminPost("install");
        setStatus("trainStatus", t("训练组件安装已开始。", "Trainer install started."), false);
        await loadAdmin(); return;
      }
      if (action === "uninstall") {
        var ok = await uiConfirm({ title: t("卸载训练组件", "Uninstall trainer"),
          message: t("不会删除训练数据集和已发布的 LoRA。", "Datasets and published LoRAs will be kept."),
          danger: true });
        if (!ok) return;
        await adminPost("uninstall"); await loadAdmin(); return;
      }
      if (action === "approve") return approve(tid);
      if (action === "reject") return reject(tid);
      if (action === "cancel") {
        var c = await uiConfirm({ title: t("停止训练", "Stop training"),
          message: t("会终止训练进程，已保存的检查点保留。", "The process stops; saved checkpoints are kept."),
          danger: true });
        if (!c) return;
        await adminPost("cancel", { project_id: tid, reason: "管理员停止" });
        await loadAdmin(); await loadTraining(false); return;
      }
      if (action === "openadmin") { openDetail(tid); return; }
      if (action === "share") {
        await adminPost("share_lora", { name: name, public: el.getAttribute("data-public") === "1" });
        await loadAdmin(); return;
      }
      if (action === "dellora") {
        var d = await uiConfirm({ title: t("删除 LoRA", "Delete LoRA"),
          message: t("会把训练出的 LoRA 移到回收站，训练记录保留。", "Moves the trained LoRA to trash."),
          ack: t("我确认", "I understand"), danger: true });
        if (!d) return;
        await adminPost("delete_lora", { name: name });
        await loadAdmin(); return;
      }
    } catch (e) { setStatus("trainStatus", e.message, true); }
  }

  /* ---------------- 事件 ---------------- */
  function wire() {
    var tab = document.getElementById("trainTab");
    if (tab) tab.addEventListener("click", function () { trainStart(); });
    var refresh = document.getElementById("trainRefresh");
    if (refresh) refresh.onclick = function () { loadTraining(true); if (S.data && S.data.admin) loadAdmin(); };
    var nw = document.getElementById("trainNew");
    if (nw) nw.onclick = openNew;
    var nc = document.getElementById("trainNewClose");
    if (nc) nc.onclick = function () { q("#trainNewPop").classList.remove("on"); };
    var ncan = document.getElementById("trainNewCancel");
    if (ncan) ncan.onclick = nc.onclick;
    var ns = document.getElementById("trainNewSave");
    if (ns) ns.onclick = createProject;
    var prof = q("#tnProfile");
    if (prof) prof.onchange = fillModels;
    var pre = q("#tnPreset");
    if (pre) pre.onchange = applyPreset;
    var td = document.getElementById("tdClose");
    if (td) td.onclick = closeDetail;
    var tgc = document.getElementById("tgClose");
    if (tgc) tgc.onclick = function () { q("#trainGalleryPop").classList.remove("on"); };
    var tgcan = document.getElementById("tgCancel");
    if (tgcan) tgcan.onclick = tgc.onclick;
    var tga = document.getElementById("tgAdd");
    if (tga) tga.onclick = addGallery;
    var grid = document.getElementById("tgGrid");
    if (grid) grid.onclick = function (e) {
      var cell = e.target.closest(".tg");
      if (!cell) return;
      var name = cell.getAttribute("data-name") || "";
      if (!name) return;
      if (S.gallerySel[name]) delete S.gallerySel[name];
      else S.gallerySel[name] = true;
      cell.classList.toggle("on", !!S.gallerySel[name]);
    };
    var proj = document.getElementById("trainProjects");
    if (proj) proj.onclick = function (e) {
      var b = e.target.closest("[data-tr]");
      if (!b) return;
      var tid = b.getAttribute("data-tid") || "";
      var act = b.getAttribute("data-tr");
      if (act === "open") return openDetail(tid);
      if (act === "submit") {
        post("submit", { project_id: tid }).then(function () { loadTraining(false); openDetail(tid); })
          .catch(function (e) { setStatus("trainStatus", e.message, true); });
        return;
      }
      if (act === "retry") {
        post("retry", { project_id: tid }).then(function () { loadTraining(false); openDetail(tid); })
          .catch(function (e) { setStatus("trainStatus", e.message, true); });
        return;
      }
      if (act === "cancel") {
        uiConfirm({ title: t("取消训练", "Cancel training"),
          message: t("确定取消这个训练？", "Cancel this training?"), danger: true })
          .then(function (ok) {
            if (!ok) return;
            return post("cancel", { project_id: tid }).then(function () {
              loadTraining(false); if (S.detailId === tid) closeDetail();
            });
          }).catch(function (e) { setStatus("trainStatus", e.message, true); });
        return;
      }
      if (act === "use") {
        useLora(tid); return;
      }
    };
    var body = document.getElementById("tdBody");
    if (body) body.onclick = function (e) {
      var b = e.target.closest("[data-td]");
      if (!b) return;
      var act = b.getAttribute("data-td");
      var p = S.detail;
      if (!p) return;
      if (act === "submit") {
        post("submit", { project_id: p.id }).then(function () { refreshDetail(true); loadTraining(false); })
          .catch(function (e) { setStatus("trainStatus", e.message, true); });
      } else if (act === "retry") {
        post("retry", { project_id: p.id }).then(function () { refreshDetail(true); loadTraining(false); })
          .catch(function (e) { setStatus("trainStatus", e.message, true); });
      } else if (act === "gallery") { openGallery(); }
      else if (act === "save") { saveDetail(); }
      else if (act === "cancel") {
        uiConfirm({ title: t("取消训练", "Cancel training"),
          message: t("确定取消？", "Are you sure?"), danger: true }).then(function (ok) {
          if (!ok) return;
          return post("cancel", { project_id: p.id }).then(function () {
            refreshDetail(true); loadTraining(false);
          });
        }).catch(function (e) { setStatus("trainStatus", e.message, true); });
      } else if (act === "delete") {
        uiConfirm({ title: t("删除训练记录", "Delete training"),
          message: t("会删除数据集/日志，已发布的 LoRA 默认保留。",
            "Deletes dataset/logs; published LoRA is kept by default."),
          ack: t("我确认", "I understand"), danger: true }).then(function (ok) {
          if (!ok) return;
          return post("delete", { project_id: p.id, delete_lora: false }).then(function () {
            closeDetail(); loadTraining(false);
          });
        }).catch(function (e) { setStatus("trainStatus", e.message, true); });
      } else if (act === "use") { useLora(p.id); }
      else if (act === "download") { downloadLora(p.id); }
      else if (act === "rmimg") {
        post("delete_image", { project_id: p.id, image_id: b.getAttribute("data-iid") })
          .then(function () { refreshDetail(true); loadTraining(false); })
          .catch(function (e) { setStatus("trainStatus", e.message, true); });
      }
    };
    var admin = document.getElementById("trainAdminContent");
    if (admin) admin.onclick = function (e) {
      var b = e.target.closest("[data-ta]");
      if (!b) return;
      adminAction(b.getAttribute("data-ta"), b);
    };
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      var pop = q("#trainDetailPop.on") || q("#trainNewPop.on") || q("#trainGalleryPop.on");
      if (pop) pop.classList.remove("on");
      if (q("#trainDetailPop.on") === null && S.detailId) closeDetail();
    });
  }

  function useLora(tid) {
    var p = (S.data.projects || []).find(function (x) { return x.id === tid; });
    if (!p) { openDetail(tid); return; }
    var name = (p.output || {}).name || "";
    if (!name) return;
    switchTab("gen");
    var done = function () {
      var modelChip = qa("#models .chip").find(function (x) {
        return x.dataset.model === p.base_model || x.textContent.indexOf(p.base_model) >= 0;
      });
      if (modelChip) modelChip.click();
      if (window.__loras) {
        loraSel[name] = true;
        renderLoras(window.__loras);
      }
      show(t("已选中训练出的 LoRA：", "Selected trained LoRA: ") + name, "done");
    };
    if (typeof loadModels === "function") loadModels().then(done).catch(done); else done();
  }
  function downloadLora(tid) {
    window.location.href = "/api/training/download?project_id=" + encodeURIComponent(tid);
  }

  /* ---------------- 启动 ---------------- */
  function boot() {
    wire();
    qa(".tabs .tab").forEach(function (x) {
      x.addEventListener("click", function () {
        if (x.dataset.view !== "train") trainStop();
      });
    });
    var tab = document.getElementById("trainTab");
    if (tab) tab.style.display = "none";
    setTimeout(function () { loadTraining(false); }, 1200);
    var qp = new URLSearchParams(location.search);
    if (qp.get("view") === "train" && qp.get("project")) {
      setTimeout(function () { openDetail(qp.get("project")); }, 1800);
    }
    setInterval(syncTab, 3000);
    setInterval(function () {
      if (!document.getElementById("view-train").classList.contains("on")) return;
      if (!S.timer) trainStart();
    }, 3000);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
  window.MGTRAIN = { load: loadTraining, open: openDetail, stop: trainStop };
})();
