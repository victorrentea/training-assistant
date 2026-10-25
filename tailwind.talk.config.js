/** @type {import('tailwindcss').Config} */
// Talk page (static/talk.html) has its own dark violet theme, so its prebuilt CSS
// is built separately from the participant one: npm run build:css:talk.
// Prebuilt rather than the Tailwind Play CDN: corporate proxies block
// cdn.tailwindcss.com and the page then renders unstyled.
module.exports = {
    content: ["./static/talk.html", "./static/talk-notes.js", "./static/emoji-float.js", "./static/tooltip.js"],
    darkMode: "class",
    plugins: [
        require('@tailwindcss/forms'),
        require('@tailwindcss/container-queries'),
    ],
    theme: {
        "extend": {
            "colors": {
                "on-tertiary": "#490010",
                "on-primary-container": "#0a0081",
                "primary-fixed": "#9396ff",
                "on-secondary-fixed-variant": "#533ea7",
                "inverse-primary": "#494bd7",
                "on-tertiary-fixed-variant": "#780021",
                "on-error-container": "#ffb2b9",
                "on-background": "#e9e1ff",
                "surface-container-highest": "#271c53",
                "inverse-surface": "#fdf8ff",
                "tertiary": "#ff6f7e",
                "on-surface-variant": "#aea5d4",
                "primary-container": "#9396ff",
                "surface": "#0f072e",
                "secondary-dim": "#a28efc",
                "surface-variant": "#271c53",
                "tertiary-container": "#fc4563",
                "surface-tint": "#a3a6ff",
                "surface-container-low": "#140b36",
                "on-surface": "#e9e1ff",
                "secondary-container": "#49339d",
                "secondary": "#a28efc",
                "on-primary": "#0f00a4",
                "on-secondary-fixed": "#361c89",
                "outline-variant": "#4a426b",
                "surface-dim": "#0f072e",
                "error-dim": "#d73357",
                "on-primary-fixed": "#000000",
                "secondary-fixed-dim": "#c8bbff",
                "background": "#0f072e",
                "on-secondary-container": "#d4c9ff",
                "on-tertiary-container": "#100001",
                "error-container": "#a70138",
                "tertiary-fixed": "#ff9099",
                "tertiary-dim": "#ff6f7e",
                "primary-dim": "#6063ee",
                "on-primary-fixed-variant": "#0e009d",
                "outline": "#78709b",
                "primary-fixed-dim": "#8387ff",
                "surface-container-lowest": "#000000",
                "secondary-fixed": "#d6cbff",
                "tertiary-fixed-dim": "#ff7986",
                "primary": "#a3a6ff",
                "inverse-on-surface": "#574f79",
                "on-tertiary-fixed": "#39000b",
                "surface-container-high": "#211749",
                "on-secondary": "#21006d",
                "surface-bright": "#2e225d",
                "surface-container": "#1b1140",
                "on-error": "#490013",
                "error": "#ff6e84"
            },
            "borderRadius": {
                "DEFAULT": "0.25rem",
                "lg": "0.5rem",
                "xl": "0.75rem",
                "full": "9999px"
            },
            "fontFamily": {
                "headline": [
                    "Space Grotesk"
                ],
                "body": [
                    "Inter"
                ],
                "label": [
                    "Inter"
                ]
            }
        }
    },
};
