/** @type {import('next').NextConfig} */
const nextConfig = {
  // Export a fully static site (HTML/JS/CSS in ./out) so it can be hosted on a Render Static
  // Site / any CDN — free, no server, no cold starts. This app is client-only (it talks to the
  // backend API from the browser), so it has no need for the Next.js server runtime.
  output: "export",
  // Static export can't use the on-demand image optimizer; serve images as-is. (No-op today
  // since the app doesn't use next/image, but keeps a future <Image> from breaking the build.)
  images: { unoptimized: true },
};

module.exports = nextConfig;
