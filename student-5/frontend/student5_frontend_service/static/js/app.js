document.addEventListener("htmx:afterSwap", function (event) {
  var shell = event.detail && event.detail.target;
  if (shell && shell.id === "app-shell" && shell.hasAttribute("data-autofocus")) {
    shell.focus({ preventScroll: true });
  }
});