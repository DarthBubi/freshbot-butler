import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Freshbot Butler",
    short_name: "Freshbot",
    description: "Gemeinsamer Küchenüberblick für deinen Haushalt",
    start_url: "/",
    display: "standalone",
    background_color: "#f5f1e8",
    theme_color: "#294936",
    lang: "de-DE",
    icons: [
      {
        src: "/icon.svg",
        type: "image/svg+xml",
        sizes: "any"
      }
    ]
  };
}
