function syncDependentControls(root = document) {
  const date = root.querySelector("#date");
  const start = root.querySelector("#start_time");
  const end = root.querySelector("#end_time");
  if (date && start && end) {
    start.required = Boolean(date.value && end.value);
    end.required = Boolean(date.value && start.value);
  }
}

document.addEventListener("DOMContentLoaded", () => syncDependentControls());
document.addEventListener("change", (event) => syncDependentControls(event.currentTarget));
document.addEventListener("htmx:afterSwap", (event) => {
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
