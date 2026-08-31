// Move focus to the swapped panel so keyboard and screen-reader users are not
// left behind when HTMX replaces the shell.
document.addEventListener("htmx:afterSwap", function (event) {
  var shell = event.detail && event.detail.target;
  if (shell && shell.id === "app-shell" && shell.hasAttribute("data-autofocus")) {
    shell.focus({ preventScroll: true });
  }
});
