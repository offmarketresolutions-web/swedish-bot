/** Tailwind CLI build (replaces the Play CDN). Build:
 *   npx -y tailwindcss@3.4.17 -c tailwind.config.js -i static/src/input.css -o static/dashboard/css/app.css --minify
 * The Nordland brand palette lives here (single source of truth) instead of an
 * inline runtime config in base.html.
 */
module.exports = {
  content: ["./templates/**/*.html"],
  theme: {
    extend: {
      colors: {
        nl: {
          primary: "#1a74bf", primaryd: "#0f4570", primaryl: "#e9f3fc",
          action: "#d9370c", actionh: "#f34616", base: "#1c1e20",
          bg: "#f1f2f3", border: "#d6d9db",
        },
      },
    },
  },
  plugins: [],
};
