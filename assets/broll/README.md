# Local b-roll library

Drop your own clips and photos here. Klip searches this folder **before** any stock API.

Tags come from folder and file names, so name them by what's in the shot:

```
assets/broll/food/warung-nasi-goreng-night.mp4
assets/broll/transport/ojek-jakarta-traffic.mp4
assets/broll/people/teman-ngobrol-cafe.jpg
```

A scene matches when at least half of its `visual.query` words appear in the path (common
words like "close", "up", "shot" are ignored). Write queries in English, or name your files
in the language you'll query in.

To force one specific file for a scene, use `"visual": {"type": "local", "path": "assets/broll/…"}`.

Media files in this folder are gitignored. Keep only footage you own or have the rights to.
