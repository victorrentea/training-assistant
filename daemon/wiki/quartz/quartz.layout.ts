import { PageLayout, SharedLayout } from "./quartz/cfg"
import * as Component from "./quartz/components"

// The summarizer's entry page is Home.md; the builder also copies it over the site root.
const isHome = (slug?: string) => slug === "index" || slug === "Home"

// components shared across all pages
export const sharedPageComponents: SharedLayout = {
  head: Component.Head(),
  header: [],
  afterBody: [],
  footer: Component.Footer({
    links: {},
  }),
}

// components for pages that display a single page (e.g. a single note)
export const defaultContentPageLayout: PageLayout = {
  beforeBody: [
    Component.ConditionalRender({
      component: Component.Breadcrumbs(),
      condition: (page) => !isHome(page.fileData.slug),
    }),
    // Home.md opens with its own H1; Quartz's title on top of it read "Home" twice.
    Component.ConditionalRender({
      component: Component.ArticleTitle(),
      condition: (page) => !isHome(page.fileData.slug),
    }),
    Component.ContentMeta(),
    Component.TagList(),
  ],
  left: [
    Component.PageTitle(),
    Component.MobileOnly(Component.Spacer()),
    Component.Flex({
      components: [
        {
          Component: Component.Search(),
          grow: true,
        },
        { Component: Component.Darkmode() },
        { Component: Component.ReaderMode() },
      ],
    }),
    Component.Explorer(),
  ],
  right: [
    Component.Graph({
      // Tag nodes doubled the node count and turned the global view into a hairball.
      // Node size, label placement and colours are patched in by patch-graph.py.
      localGraph: {
        showTags: false,
        repelForce: 1,
        linkDistance: 45,
        fontSize: 0.5,
      },
      globalGraph: {
        showTags: false,
        enableRadial: false,
        repelForce: 5,
        centerForce: 0.05,
        linkDistance: 110,
        fontSize: 0.6,
      },
    }),
    Component.DesktopOnly(Component.TableOfContents()),
    Component.Backlinks(),
  ],
}

// components for pages that display lists of pages  (e.g. tags or folders)
export const defaultListPageLayout: PageLayout = {
  beforeBody: [Component.Breadcrumbs(), Component.ArticleTitle(), Component.ContentMeta()],
  left: [
    Component.PageTitle(),
    Component.MobileOnly(Component.Spacer()),
    Component.Flex({
      components: [
        {
          Component: Component.Search(),
          grow: true,
        },
        { Component: Component.Darkmode() },
      ],
    }),
    Component.Explorer(),
  ],
  right: [],
}
