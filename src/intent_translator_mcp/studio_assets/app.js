const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const copy = {
  zh: {
    composerKicker: "原话",
    composerTitle: "你现在想做什么？",
    resultKicker: "编译结果",
    inspectorTitle: "当前理解",
    intentLabel: "自然语言",
    placeholder: "例如：继续完善本地测试，不上传 GitHub",
    contextSummary: "当前上下文",
    contextLabel: "最近背景",
    pendingLabel: "上一条具体待办",
    compile: "确认理解",
    compiling: "正在确认",
    local: "本地处理",
    empty: "等待输入",
    interpretation: "请选择更接近的一项",
    skill: "准备调用",
    noSkill: "无专用 Skill",
    permission: "执行边界",
    why: "为何询问",
    source: "原话对应",
    memory: "使用的本地来源",
    version: "当前运行",
    restart: "需要重启",
    debateSummary: "查看尖锐审查状态",
    debateReady: "本次可按需查看完整尖锐审查。",
    debateOff: "本次没有触发尖锐审查。",
    advanced: "高级信息",
    execute: "可执行当前动作",
    wait: "等待确认，不执行",
    answerOnly: "只回答，不执行动作",
    notExecutable: "当前不执行",
    blocked: "已阻止",
    noQuestion: "当前理解明确，无需追问",
    noSourceMap: "没有不明显的转换",
    noMemory: "未使用个人记忆",
    runtimeActive: "已连接本地运行时",
    runtimeStale: "运行版本已过期",
    runtimeDegraded: "基础模式",
    disconnected: "本地接口未连接，当前保护未启用",
    localOnly: "本地处理 · 无云增强",
    localEnhanced: "本地处理 · 可选增强已配置",
    allWrong: "都不是，用一句话纠正",
    correctionComparison: "纠正前：{before}",
    examples: ["继续任务", "不发布", "选对 Skill", "纠正后复现"],
    memoryKinds: {
      memory: "记忆记录",
      correction: "纠错记录",
      "local-profile": "本地设置",
      "task-state": "本地任务状态",
    },
  },
  en: {
    composerKicker: "Original wording",
    composerTitle: "What do you want to do now?",
    resultKicker: "Compiled result",
    inspectorTitle: "Current understanding",
    intentLabel: "Natural language",
    placeholder: "Example: continue the local tests, do not upload to GitHub",
    contextSummary: "Current context",
    contextLabel: "Recent background",
    pendingLabel: "Specific previous action",
    compile: "Confirm understanding",
    compiling: "Checking",
    local: "Local processing",
    empty: "Waiting for input",
    interpretation: "Choose the closest result",
    skill: "Prepared tool",
    noSkill: "No specialized Skill",
    permission: "Action boundary",
    why: "Why it asks",
    source: "Wording map",
    memory: "Local sources used",
    version: "Running version",
    restart: "Restart required",
    debateSummary: "View critical review status",
    debateReady: "A full critical review is available on request.",
    debateOff: "No critical review was triggered.",
    advanced: "Advanced information",
    execute: "Current action can run",
    wait: "Waiting for confirmation",
    answerOnly: "Answer only; no action",
    notExecutable: "No action will run",
    blocked: "Blocked",
    noQuestion: "The current meaning is clear",
    noSourceMap: "No non-obvious transformation",
    noMemory: "No personal memory used",
    runtimeActive: "Local runtime connected",
    runtimeStale: "Running version is stale",
    runtimeDegraded: "Base mode",
    disconnected: "Local interface is disconnected; protection is not active",
    localOnly: "Local processing · no cloud enhancement",
    localEnhanced: "Local processing · optional enhancement configured",
    allWrong: "None of these; correct in one sentence",
    correctionComparison: "Before correction: {before}",
    examples: ["Continue", "Do not publish", "Choose Skill", "Correction replay"],
    memoryKinds: {
      memory: "Memory record",
      correction: "Correction record",
      "local-profile": "Local settings",
      "task-state": "Local task state",
    },
  },
};

const examples = {
  continue: {
    utterance: "继续",
    context: "主任务正在完善本地 Alpha 测试。",
    pending: "继续完善本地测试，不上传 GitHub",
  },
  negative: {
    utterance: "好，我们先比较方案，不要发布",
    context: "上一条提到以后可能发布到 GitHub。",
    pending: "",
  },
  route: {
    utterance: "帮我搜索 GitHub 上高星的 Agent Skill",
    context: "",
    pending: "",
  },
};

let language = "zh";
let lastResult = null;
let previousResult = null;
let activeExample = null;

function t(key) {
  return copy[language][key];
}

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function applyLanguage() {
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  setText("#composer-kicker", t("composerKicker"));
  setText("#composer-title", t("composerTitle"));
  setText("#result-kicker", t("resultKicker"));
  setText("#inspector-title", t("inspectorTitle"));
  setText("#intent-label", t("intentLabel"));
  $("#intent-input").placeholder = t("placeholder");
  setText("#context-summary", t("contextSummary"));
  setText("#context-label", t("contextLabel"));
  setText("#pending-label", t("pendingLabel"));
  setText("#compile-button", t("compile"));
  setText("#local-mode-label", t("local"));
  setText("#empty-result", t("empty"));
  setText("#interpretation-title", t("interpretation"));
  setText("#skill-title", t("skill"));
  setText("#permission-title", t("permission"));
  setText("#why-title", t("why"));
  setText("#source-title", t("source"));
  setText("#memory-title", t("memory"));
  setText("#version-title", t("version"));
  setText("#restart-badge", t("restart"));
  setText("#debate-summary", t("debateSummary"));
  setText("#advanced-summary", t("advanced"));
  $("#language-toggle").textContent = language === "zh" ? "EN" : "中";
  $$("[data-example]").forEach((button, index) => {
    button.textContent = t("examples")[index];
  });
  if (lastResult) renderResult(lastResult);
}

function runtimeLabel(runtime) {
  const version = runtime?.versions?.actual_runtime || "?";
  if (runtime?.state === "active") return `${t("runtimeActive")} ${version}`;
  if (runtime?.state === "stale") return `${t("runtimeStale")} ${version}`;
  return `${t("runtimeDegraded")} ${version}`;
}

function setRuntime(runtime) {
  const state = runtime?.state || "degraded";
  $("#runtime-dot").className = `status-dot ${state}`;
  $("#runtime-state").textContent = runtimeLabel(runtime);
}

async function loadStatus() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error("status unavailable");
    const status = await response.json();
    setRuntime(status.runtime);
    $("#local-mode-label").textContent = status.semantic_enhancement.configured
      ? t("localEnhanced")
      : t("localOnly");
    $("#connection-alert").hidden = true;
  } catch (error) {
    $("#runtime-dot").className = "status-dot error";
    $("#runtime-state").textContent = t("disconnected");
    $("#connection-alert").textContent = t("disconnected");
    $("#connection-alert").hidden = false;
  }
}

function permissionLabel(auth) {
  if (auth.action_state === "blocked") return t("blocked");
  if (auth.action_state === "executable") return t("execute");
  if (auth.action_state === "waiting-confirmation") return t("wait");
  if (auth.action_state === "answer-only") return t("answerOnly");
  return t("notExecutable");
}

function renderInterpretations(data) {
  const section = $("#interpretation-section");
  const options = $("#interpretation-options");
  options.replaceChildren();
  if (!data.interpretations.required) {
    section.hidden = true;
    return;
  }
  data.interpretations.candidates.forEach((candidate) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = candidate.text;
    button.className = candidate.recommended ? "recommended" : "";
    button.addEventListener("click", () => {
      $("#intent-input").value = candidate.text;
      section.hidden = true;
    });
    options.appendChild(button);
  });
  const none = document.createElement("button");
  none.type = "button";
  none.textContent = t("allWrong");
  none.addEventListener("click", () => $("#intent-input").focus());
  options.appendChild(none);
  section.hidden = false;
}

function renderWhy(data) {
  const list = $("#why-ask");
  list.replaceChildren();
  const reasons = data.why_ask.length ? data.why_ask : [t("noQuestion")];
  list.className = data.why_ask.length ? "plain-list" : "plain-list empty";
  reasons.forEach((reason) => {
    const item = document.createElement("li");
    item.textContent = reason;
    list.appendChild(item);
  });
}

function renderSourceMap(data) {
  const root = $("#source-map");
  root.replaceChildren();
  if (!data.source_map.length) {
    const empty = document.createElement("p");
    empty.className = "comparison-text";
    empty.textContent = t("noSourceMap");
    root.appendChild(empty);
    return;
  }
  data.source_map.forEach((mapping) => {
    const row = document.createElement("div");
    row.className = "source-row";
    const original = document.createElement("span");
    original.textContent = mapping.original;
    const arrow = document.createElement("span");
    arrow.className = "source-arrow";
    arrow.textContent = "→";
    const compiled = document.createElement("span");
    compiled.textContent = mapping.compiled;
    row.append(original, arrow, compiled);
    root.appendChild(row);
  });
}

function renderMemory(data) {
  const root = $("#memory-sources");
  root.replaceChildren();
  if (!data.memory_sources.length) {
    const empty = document.createElement("span");
    empty.className = "comparison-text";
    empty.textContent = t("noMemory");
    root.appendChild(empty);
    return;
  }
  data.memory_sources.forEach((source) => {
    const chip = document.createElement("span");
    chip.className = "source-chip";
    const label = t("memoryKinds")[source.kind] || source.kind;
    chip.textContent = source.id ? `${label} #${source.id}` : label;
    root.appendChild(chip);
  });
}

function renderResult(data, comparison = "") {
  lastResult = data;
  $("#empty-result").hidden = true;
  $("#result-content").hidden = false;
  $("#undo-interpretation").disabled = !previousResult;
  $("#understanding-text").textContent = data.understanding;
  $("#selected-skill").textContent = data.selected_skill || t("noSkill");
  $("#permission-state").textContent = permissionLabel(data.authorization);
  const comparisonElement = $("#comparison-text");
  comparisonElement.textContent = comparison;
  comparisonElement.hidden = !comparison;
  renderInterpretations(data);
  renderWhy(data);
  renderSourceMap(data);
  renderMemory(data);
  setRuntime(data.runtime);
  $("#runtime-detail").textContent = runtimeLabel(data.runtime);
  $("#restart-badge").hidden = !data.runtime.restart_required;
  $("#debate-content").textContent = data.debate.recommended ? t("debateReady") : t("debateOff");
  $("#advanced-content").textContent = JSON.stringify(data.advanced, null, 2);
}

async function compileIntent() {
  const utterance = $("#intent-input").value.trim();
  if (!utterance) {
    $("#intent-input").focus();
    return;
  }
  const button = $("#compile-button");
  button.disabled = true;
  button.textContent = t("compiling");
  try {
    const response = await fetch("/api/compile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        utterance,
        context: $("#context-input").value,
        pending_action: $("#pending-input").value,
        semantic_mode: "auto",
      }),
    });
    if (!response.ok) throw new Error("compile failed");
    previousResult = lastResult;
    renderResult(await response.json());
  } catch (error) {
    $("#connection-alert").textContent = t("disconnected");
    $("#connection-alert").hidden = false;
    $("#runtime-dot").className = "status-dot error";
  } finally {
    button.disabled = false;
    button.textContent = t("compile");
  }
}

async function runCorrectionDemo() {
  const button = $("#compile-button");
  button.disabled = true;
  button.textContent = t("compiling");
  try {
    const response = await fetch("/api/demo/correction", { cache: "no-store" });
    if (!response.ok) throw new Error("demo failed");
    const result = await response.json();
    previousResult = lastResult;
    $("#intent-input").value = "走起";
    renderResult(
      result.after,
      t("correctionComparison").replace("{before}", result.before.understanding),
    );
  } finally {
    button.disabled = false;
    button.textContent = t("compile");
  }
}

function selectExample(name) {
  activeExample = name;
  $$("[data-example]").forEach((button) => {
    button.classList.toggle("active", button.dataset.example === name);
  });
  if (name === "correction") {
    runCorrectionDemo();
    return;
  }
  const example = examples[name];
  $("#intent-input").value = example.utterance;
  $("#context-input").value = example.context;
  $("#pending-input").value = example.pending;
  compileIntent();
}

function resetSession() {
  activeExample = null;
  lastResult = null;
  previousResult = null;
  $("#intent-input").value = "";
  $("#context-input").value = "";
  $("#pending-input").value = "";
  $("#result-content").hidden = true;
  $("#empty-result").hidden = false;
  $("#undo-interpretation").disabled = true;
  $$("[data-example]").forEach((button) => button.classList.remove("active"));
}

$("#compile-button").addEventListener("click", compileIntent);
$("#reset-session").addEventListener("click", resetSession);
$("#language-toggle").addEventListener("click", () => {
  language = language === "zh" ? "en" : "zh";
  applyLanguage();
  loadStatus();
});
$("#undo-interpretation").addEventListener("click", () => {
  if (!previousResult) return;
  const current = lastResult;
  renderResult(previousResult);
  previousResult = current;
});
$$('[data-example]').forEach((button) => {
  button.addEventListener("click", () => selectExample(button.dataset.example));
});

applyLanguage();
loadStatus();
