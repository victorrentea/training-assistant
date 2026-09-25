import { QuartzConfig } from "./quartz/cfg"
import * as Plugin from "./quartz/plugins"

/**
 * Quartz 4 Configuration
 *
 * See https://quartz.jzhao.xyz/configuration for more information.
 */
const config: QuartzConfig = {
  configuration: {
    // The daemon passes the session name; one build per session, never shared.
    pageTitle: process.env.WIKI_TITLE ?? "Workshop Wiki",
    pageTitleSuffix: "",
    enableSPA: true,
    enablePopovers: true,
    analytics: null,
    locale: "en-US",
    // Served under /{session_id}/wiki-site/ — Quartz links are relative, so this only feeds sitemap/RSS.
    baseUrl: "interact.victorrentea.ro",
    ignorePatterns: ["private", "templates", ".obsidian"],
    defaultDateType: "modified",
    theme: {
      fontOrigin: "googleFonts",
      cdnCaching: true,
      typography: {
        header: "Schibsted Grotesk",
        body: "Source Sans Pro",
        code: "IBM Plex Mono",
      },
      // The participant page's MD3 palette (static/participant-theme.css), so the
      // wiki inside its iframe reads as part of the same app.
      colors: {
        lightMode: {
          light: "#f7f9fb",
          lightgray: "#e0e7ec",
          gray: "#a9b4ba",
          darkgray: "#4e5a60",
          dark: "#2a3439",
          secondary: "#4555ba",
          tertiary: "#7f8ddc",
          highlight: "rgba(69, 85, 186, 0.10)",
          textHighlight: "#fff23688",
        },
        darkMode: {
          light: "#12151a",
          lightgray: "#2c333b",
          gray: "#5f6a72",
          darkgray: "#d0d8dd",
          dark: "#dce4e9",
          secondary: "#bcc4ff",
          tertiary: "#8f9be8",
          highlight: "rgba(188, 196, 255, 0.12)",
          textHighlight: "#b3aa0288",
        },
      },
    },
  },
  plugins: {
    transformers: [
      Plugin.FrontMatter(),
      Plugin.CreatedModifiedDate({
        // The build runs on a temp copy of the vault, outside any git repo.
        priority: ["frontmatter", "filesystem"],
      }),
      Plugin.SyntaxHighlighting({
        theme: {
          light: "github-light",
          dark: "github-dark",
        },
        keepBackground: false,
      }),
      Plugin.ObsidianFlavoredMarkdown({ enableInHtmlEmbed: false }),
      Plugin.GitHubFlavoredMarkdown(),
      Plugin.TableOfContents(),
      Plugin.CrawlLinks({ markdownLinkResolution: "shortest" }),
      Plugin.Description(),
      // No Latex: session notes quote prices ("$100/month … $5/day"), and $…$ turned them into math.
    ],
    filters: [Plugin.RemoveDrafts()],
    emitters: [
      Plugin.AliasRedirects(),
      Plugin.ComponentResources(),
      Plugin.ContentPage(),
      Plugin.FolderPage(),
      Plugin.TagPage(),
      Plugin.ContentIndex({
        enableSiteMap: true,
        enableRSS: true,
      }),
      Plugin.Assets(),
      Plugin.Static(),
      Plugin.Favicon(),
      Plugin.NotFoundPage(),
      // No CustomOgImages: it is the slowest emitter and private session pages are never shared as cards.
    ],
  },
}

export default config
