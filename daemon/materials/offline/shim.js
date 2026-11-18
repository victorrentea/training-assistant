// The participant page opened from disk, after the session: there is no server, so this
// answers the page's requests from the snapshot bundled in offline-data.js and turns the
// live-only parts off (training-assistant daemon/materials/offline_site.py). Loaded first
// thing in <head>, before any script of the page runs.
(function () {
  var DATA = window.__OFFLINE__ || { api: {}, decks: [], wiki: false }
  var api = DATA.api || {}

  // A returning participant: skip the name gate, the snapshot has no one to register.
  try { localStorage.setItem("workshop_participant_uuid_seen", "1") } catch (e) {}

  var domReady = new Promise(function (resolve) {
    if (document.readyState !== "loading") resolve()
    else document.addEventListener("DOMContentLoaded", resolve)
  })

  function json(body, status) {
    return new Response(JSON.stringify(body), {
      status: status || 200,
      headers: { "Content-Type": "application/json" },
    })
  }

  var realFetch = window.fetch.bind(window)
  window.fetch = function (input, init) {
    var raw = input instanceof Request ? input.url : String(input)
    var url = new URL(raw, location.href)
    if (url.protocol === "http:" || url.protocol === "https:") return realFetch(input, init)
    var method = ((init && init.method) || (input instanceof Request && input.method) || "GET").toUpperCase()
    var match = url.pathname.match(/\/api\/(.+)$/)
    // Not before the page's own scripts have all run: they are what handles the answer.
    return domReady.then(function () {
      if (!match) return json({ error: "Not available offline" }, 404)
      var key = match[1].replace(/^participant\//, "")
      if (method === "GET") {
        return key in api ? json(api[key]) : json({ error: "Not available offline" }, 404)
      }
      if (key === "rejoin" || key === "register") return json({ name: DATA.viewer || "" })
      return new Response(null, { status: 204 })
    })
  }

  // A socket that opens and then stays quiet: the page shows what the snapshot holds
  // and never decides it lost its connection.
  function QuietSocket() {
    var self = this
    self.readyState = QuietSocket.CONNECTING
    setTimeout(function () {
      self.readyState = QuietSocket.OPEN
      if (typeof self.onopen === "function") self.onopen({})
    }, 0)
  }
  QuietSocket.CONNECTING = 0
  QuietSocket.OPEN = 1
  QuietSocket.CLOSING = 2
  QuietSocket.CLOSED = 3
  QuietSocket.prototype.send = function () {}
  QuietSocket.prototype.close = function () { this.readyState = QuietSocket.CLOSED }
  QuietSocket.prototype.addEventListener = function () {}
  QuietSocket.prototype.removeEventListener = function () {}
  window.WebSocket = QuietSocket

  function decksMenu() {
    var nav = document.querySelector('[data-nav="slides"]')
    if (!nav) return
    var box = nav.parentElement
    if (!DATA.decks.length) { box.style.display = "none"; return }
    var list = document.getElementById("topics-inner")
    var holder = box.querySelector(".topics-list")
    if (holder) { holder.style.maxHeight = "none"; holder.style.overflow = "visible" }
    nav.onclick = null
    nav.style.cursor = "default"
    list.innerHTML = ""
    DATA.decks.forEach(function (deck) {
      var link = document.createElement("a")
      link.href = deck.href
      link.target = "_blank"
      link.rel = "noopener"
      link.className = "topic-item pl-4 pr-2 py-1.5 text-sm text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high cursor-pointer rounded-lg flex items-center gap-2 min-w-0"
      link.dataset.tip = "Open " + deck.filename
      var name = document.createElement("span")
      name.className = "truncate flex-1 font-semibold"
      name.textContent = deck.title
      var icon = document.createElement("span")
      icon.className = "material-symbols-outlined flex-shrink-0"
      icon.style.fontSize = "16px"
      icon.textContent = "picture_as_pdf"
      link.appendChild(name)
      link.appendChild(icon)
      list.appendChild(link)
    })
  }

  function banner() {
    var bar = document.createElement("div")
    bar.id = "offline-banner"
    bar.textContent = "Offline copy" + (DATA.session ? " of " + DATA.session : "") +
      (DATA.saved ? " · saved " + DATA.saved : "") + " · read-only"
    // In the sidebar, where the participant's own name sits in a live session.
    var profile = document.getElementById("profile-card")
    if (profile && profile.parentElement) profile.parentElement.insertBefore(bar, profile)
    else document.body.appendChild(bar)
  }

  domReady.then(function () {
    document.documentElement.classList.add("offline-copy")
    // The page's own functions are globals: these stand in for the ones that need a server.
    window._wikiUrl = function () { return "wiki/index.html" }
    window._showAccessToast = function () {}
    window._applyGdriveToast = function () {}
    window.loadSlidesCatalog = function () { decksMenu(); return Promise.resolve() }
    window._setPastSlidesBadge = function () {}
    // The row blinks until the zip is taken; whoever reads this copy already has it.
    window._applyZipReminder = function () {}
    // "Download all" has no zip to build any more: it opens the Drive folder instead.
    var drive = (api.state || {}).gdrive_url
    window.downloadMaterialsZip = function () { if (drive) window.open(drive, "_blank", "noopener") }
    if (!drive) document.documentElement.classList.add("offline-no-drive")
    banner()
  })
})()
