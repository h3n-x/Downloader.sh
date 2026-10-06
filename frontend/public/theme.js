// Runs synchronously in <head> (external file: CSP forbids inline scripts) to apply
// the stored theme before first paint, then wires the header toggle.
(() => {
  const KEY = "theme";
  const root = document.documentElement;
  const read = () => {
    try {
      return localStorage.getItem(KEY);
    } catch {
      return null;
    }
  };
  const apply = (value) => {
    if (value === "light" || value === "dark") root.dataset.theme = value;
    else delete root.dataset.theme;
  };
  apply(read());
  document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("theme-toggle");
    if (!button) return;
    const order = ["system", "light", "dark"];
    const sync = () => {
      const current = read() ?? "system";
      button.dataset.mode = current;
      const label = button.dataset[`label${current[0].toUpperCase()}${current.slice(1)}`];
      button.querySelector("[data-theme-label]").textContent = label;
    };
    button.hidden = false;
    sync();
    button.addEventListener("click", () => {
      const next = order[(order.indexOf(read() ?? "system") + 1) % order.length];
      try {
        if (next === "system") localStorage.removeItem(KEY);
        else localStorage.setItem(KEY, next);
      } catch {}
      apply(next);
      sync();
    });
  });
})();
