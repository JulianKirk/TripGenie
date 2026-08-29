document.addEventListener("htmx:beforeSwap", (event) => {
  const { xhr } = event.detail;
  if (!xhr) {
    return;
  }

  if (xhr.status >= 400) {
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  }
});

document.addEventListener("htmx:beforeRequest", () => {
  const shell = document.getElementById("app-shell");
  if (shell) {
    shell.setAttribute("aria-busy", "true");
  }
});

document.addEventListener("htmx:afterRequest", () => {
  const shell = document.getElementById("app-shell");
  if (shell) {
    shell.removeAttribute("aria-busy");
  }
});

document.addEventListener("htmx:afterSwap", (event) => {
  const target = event.detail.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const focusTarget =
    target.querySelector("[data-autofocus]") ??
    target.querySelector("h1, h2, h3, button, a, input, select, textarea");

  if (!focusTarget || !(focusTarget instanceof HTMLElement)) {
    return;
  }

  if (!focusTarget.hasAttribute("tabindex")) {
    focusTarget.setAttribute("tabindex", "-1");
  }

  focusTarget.focus();
});
