function syncDependentControls(root = document) {
  const date = root.querySelector("#date");
  const start = root.querySelector("#start_time");
  const end = root.querySelector("#end_time");
  if (date && start && end) {
    start.required = Boolean(date.value && end.value);
    end.required = Boolean(date.value && start.value);
  }
}

// Smart Planner polling re-renders its stages; keep what the user expanded or
// collapsed, and only open a stage automatically when it starts running.
let plannerDetailsState = null;

function plannerDetailsKey(details) {
  if (details.id) return details.id;
  const owner = details.parentElement?.closest("[id]");
  if (!owner) return null;
  const index = [...owner.querySelectorAll("details:not([id])")].indexOf(details);
  return `${owner.id}/${index}`;
}

function capturePlannerDetails(planner) {
  const state = new Map();
  planner.querySelectorAll("details").forEach((details) => {
    const key = plannerDetailsKey(details);
    if (key) state.set(key, { open: details.open, status: details.dataset.stageStatus });
  });
  return state;
}

function restorePlannerDetails(planner, state) {
  planner.querySelectorAll("details").forEach((details) => {
    const previous = state.get(plannerDetailsKey(details));
    if (!previous) return;
    const started = details.dataset.stageStatus === "running" && previous.status !== "running";
    details.open = started || previous.open;
  });
}

document.addEventListener("htmx:beforeSwap", (event) => {
  const target = event.detail.target;
  plannerDetailsState = target?.id === "planner-result" ? capturePlannerDetails(target) : null;
});

document.addEventListener("DOMContentLoaded", () => syncDependentControls());
document.addEventListener("change", (event) => syncDependentControls(event.currentTarget));
document.addEventListener("htmx:afterSwap", (event) => {
  const planner = document.getElementById("planner-result");
  if (plannerDetailsState && planner) restorePlannerDetails(planner, plannerDetailsState);
  plannerDetailsState = null;
  syncDependentControls(event.target);
  const dialog = event.target.matches?.("dialog")
    ? event.target
    : event.target.querySelector?.("dialog");
  if (dialog && !dialog.open) dialog.showModal();
});
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-close-dialog]")) event.target.closest("dialog")?.close();
  if (event.target.closest("[data-remove-schedule]")) event.target.closest(".schedule-row")?.remove();
  if (event.target.closest("[data-add-schedule]")) {
    const rows = document.querySelector("#schedule-rows");
    const template = document.querySelector("#schedule-row-template");
    if (rows && template) {
      const row = template.content.firstElementChild.cloneNode(true);
      const indexes = [...rows.querySelectorAll('[name^="schedules."]')]
        .map((control) => Number(control.name.split(".")[1]))
        .filter(Number.isFinite);
      const index = indexes.length ? Math.max(...indexes) + 1 : 0;
      row.querySelectorAll("input, select").forEach((control) => {
        control.name = control.name.replace("__INDEX__", String(index));
      });
      rows.append(row);
    }
  }
});
