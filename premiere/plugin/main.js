const { entrypoints } = require("uxp");
const { localFileSystem } = require("uxp").storage;
const ppro = require("premierepro");

const ENGINE_ENDPOINTS = [
  "https://127.0.0.1:8765",
  "http://127.0.0.1:8765"
];

let packageEntry = null;
let audioEntry = null;
let finalVideoPath = null;
let initialized = false;

function $(id) { return document.getElementById(id); }

function setStatus(label, progress, message) {
  const percent = Math.max(0, Math.min(100, Math.round(Number(progress || 0) * 100)));
  $("status-label").textContent = label;
  $("status-percent").textContent = `${percent}%`;
  $("progress-fill").style.width = `${percent}%`;
  $("status-message").textContent = message || "";
}

function showError(error) {
  const box = $("error");
  box.textContent = String(error && error.message ? error.message : error);
  box.hidden = false;
}

function clearError() {
  $("error").hidden = true;
  $("error").textContent = "";
}

function refreshGenerate() {
  $("generate").disabled = !(packageEntry && audioEntry);
}

async function pickPackageFolder() {
  clearError();
  try {
    const entry = await localFileSystem.getFolder();
    if (!entry) return;
    packageEntry = entry;
    $("package-path").textContent = entry.nativePath || entry.name;
    refreshGenerate();
  } catch (error) { showError(error); }
}

async function pickPackageZip() {
  clearError();
  try {
    const entry = await localFileSystem.getFileForOpening({ allowMultiple: false });
    if (!entry) return;
    if (!String(entry.name || "").toLowerCase().endsWith(".zip")) {
      throw new Error("Choose a Final Package .zip file.");
    }
    packageEntry = entry;
    $("package-path").textContent = entry.nativePath || entry.name;
    refreshGenerate();
  } catch (error) { showError(error); }
}

async function pickAudio() {
  clearError();
  try {
    const entry = await localFileSystem.getFileForOpening({ allowMultiple: false });
    if (!entry) return;
    audioEntry = entry;
    $("audio-path").textContent = entry.nativePath || entry.name;
    refreshGenerate();
  } catch (error) { showError(error); }
}

async function engineRequest(path, options = {}) {
  let lastError = null;
  for (const base of ENGINE_ENDPOINTS) {
    try {
      const response = await fetch(`${base}${path}`, options);
      if (!response.ok) {
        throw new Error(`HEXA engine returned ${response.status}: ${await response.text()}`);
      }
      return await response.json();
    } catch (error) {
      lastError = error;
    }
  }
  throw new Error(`HEXA engine is not reachable. ${lastError || ""}`);
}

async function checkEngine() {
  try {
    await engineRequest("/health");
    $("engine-dot").className = "dot online";
  } catch (_) {
    $("engine-dot").className = "dot offline";
  }
}

async function generate() {
  clearError();
  finalVideoPath = null;
  $("add-to-timeline").hidden = true;
  $("generate").disabled = true;
  setStatus("Starting", 0.02, "Submitting job to HEXA…");
  try {
    const job = await engineRequest("/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        package_path: packageEntry.nativePath,
        audio_path: audioEntry.nativePath
      })
    });
    await poll(job.id);
  } catch (error) {
    setStatus("Failed", 1, "Generation failed.");
    showError(error);
  } finally {
    refreshGenerate();
  }
}

async function poll(jobId) {
  for (;;) {
    const job = await engineRequest(`/jobs/${jobId}`);
    setStatus(job.state, job.progress, job.message || "Processing…");
    if (job.state === "completed") {
      finalVideoPath = job.output_path;
      $("add-to-timeline").hidden = !finalVideoPath;
      return;
    }
    if (job.state === "failed") {
      throw new Error(`${job.error_code || "HEXA_ERROR"}: ${job.message || "Generation failed"}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}

async function addToTimeline() {
  if (!finalVideoPath) return;
  clearError();
  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error("Open a Premiere project first.");

    const targetBin = await project.getInsertionBin();
    const before = await targetBin.getItems();
    const beforeIds = new Set();
    for (const item of before) beforeIds.add(await item.getId());

    const imported = await project.importFiles([finalVideoPath], true, targetBin, false);
    if (!imported) throw new Error("Premiere could not import the HEXA final video.");

    const after = await targetBin.getItems();
    let projectItem = null;
    for (const item of after) {
      const id = await item.getId();
      if (!beforeIds.has(id)) {
        projectItem = item;
        break;
      }
    }
    if (!projectItem) {
      const basename = finalVideoPath.split(/[\\/]/).pop();
      projectItem = after.find((item) => item.name === basename) || null;
    }
    if (!projectItem) throw new Error("The imported HEXA clip could not be located in Premiere.");

    const sequence = await project.getActiveSequence();
    if (!sequence) {
      setStatus("Imported", 1, "Video imported. Open a sequence to place it on the timeline.");
      return;
    }

    const editor = ppro.SequenceEditor.getEditor(sequence);
    const position = await sequence.getPlayerPosition();
    let transactionOk = false;
    project.lockedAccess(() => {
      transactionOk = project.executeTransaction((compoundAction) => {
        const action = editor.createInsertProjectItemAction(projectItem, position, 0, 0, false);
        compoundAction.addAction(action);
      }, "Add HEXA Final to Timeline");
    });
    if (!transactionOk) throw new Error("Premiere rejected the timeline insert action.");
    setStatus("Done", 1, "HEXA final added to the active timeline.");
  } catch (error) {
    showError(error);
  }
}

function initialize() {
  if (initialized) return;
  initialized = true;
  $("pick-package-folder").addEventListener("click", pickPackageFolder);
  $("pick-package-zip").addEventListener("click", pickPackageZip);
  $("pick-audio").addEventListener("click", pickAudio);
  $("generate").addEventListener("click", generate);
  $("add-to-timeline").addEventListener("click", addToTimeline);
  checkEngine();
  setInterval(checkEngine, 5000);
}

entrypoints.setup({
  panels: {
    "hexa-panel": {
      create() { initialize(); },
      show() { initialize(); }
    }
  }
});
