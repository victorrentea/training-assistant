// Replaces Quartz's own script (builder.py copies it over): the wiki takes the theme
// picked on the participant page (static/theme.js), live, in the iframe or a tab of its
// own, and an OS switch never turns into a stored choice — Quartz's did, which then
// stuck to "dark" or "light" for good. Quartz's toggle stays working, under the same key.
const KEY = "interact-theme"
const os = window.matchMedia("(prefers-color-scheme: dark)")

const pick = (): "light" | "dark" => {
  const saved = localStorage.getItem(KEY)
  if (saved === "light" || saved === "dark") return saved
  return os.matches ? "dark" : "light"
}

const apply = () => {
  const theme = pick()
  const root = document.documentElement
  if (root.getAttribute("saved-theme") === theme) return
  root.setAttribute("saved-theme", theme)
  root.style.colorScheme = theme
  document.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }))
}

document.documentElement.setAttribute("saved-theme", pick())
document.documentElement.style.colorScheme = pick()
os.addEventListener("change", apply)
window.addEventListener("storage", (e) => {
  if (e.key === KEY || e.key === null) apply()
})

document.addEventListener("nav", () => {
  const toggle = () => {
    const current = document.documentElement.getAttribute("saved-theme")
    localStorage.setItem(KEY, current === "dark" ? "light" : "dark")
    apply()
  }
  for (const button of document.getElementsByClassName("darkmode")) {
    button.addEventListener("click", toggle)
    window.addCleanup(() => button.removeEventListener("click", toggle))
  }
})
