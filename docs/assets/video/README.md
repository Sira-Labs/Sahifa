# The explainer video

Source of `site/assets/video/sahifa-explainer.*`, the 93-second narrated video on the product
page. The animation is one canvas page, `sahifa-explainer.html`: `render(t)` draws the frame at
`t` seconds and depends on nothing else, so frames can be captured one by one. Scene starts are in
`SCENES` near the end of the file; they are timed to the narration.

## Re-render

Needs Node with Playwright, Chromium and ffmpeg. Work in a scratch folder, not in the repo.

1. **Fonts.** Headless Chromium may not reach Google Fonts, so the page loads them from
   `fonts/fonts.css`. Fetch the site's fonts (Bricolage Grotesque, Figtree, IBM Plex Mono, Noto Kufi
   Arabic) as woff2 with a browser user agent, save them next to a `fonts.css` of local
   `@font-face` rules, and check the names match `F` in the page.
2. **Look at stills** before the full render: `node capture.cjs stills 6,20,33,46,57,68,80,89`
   writes PNGs to `stills/`.
3. **Frames:** `node capture.cjs frames 30` writes 2,802 JPEGs to `frames/` (a few minutes).
   Set `CHROMIUM` to the browser binary if Playwright's default is not installed.
4. **Narration:** ElevenLabs, voice "Jonathan – Warm Executive Narrator" (the one the Tabayyun video
   uses), model `eleven_v4`, the text of `narration.md` in one take. Each paragraph is cut at a
   pause and placed at its scene, then the track is normalised to -16 LUFS:

   | Paragraph | Cut from the take (s) | Placed at (s) |
   |---|---|---|
   | 1 | 0.00 – 11.10 | 0.8 |
   | 2 | 11.30 – 24.75 | 12.6 |
   | 3 | 25.20 – 36.42 | 26.8 |
   | 4 | 36.50 – 50.20 | 38.6 |
   | 5 | 50.30 – 58.48 | 52.8 |
   | 6 | 58.60 – 67.70 | 62.0 |
   | 7 | 67.85 – 81.23 | 72.2 |
   | 8 | 81.40 – 85.82 | 86.2 |

   With a new take the cut points change: find the pauses (`silencedetect`) and keep each cut
   inside one.
5. **Encode** (`mix.wav` is the placed narration):

   ```bash
   ffmpeg -framerate 30 -i frames/f%05d.jpg -i mix.wav -map 0:v -map 1:a -c:v libx264 -pix_fmt yuv420p \
     -crf 25 -preset slow -tune animation -c:a aac -b:a 128k -movflags +faststart -shortest sahifa-explainer.mp4
   ffmpeg -framerate 30 -i frames/f%05d.jpg -i mix.wav -map 0:v -map 1:a -c:v libvpx-vp9 -crf 36 -b:v 0 \
     -row-mt 1 -pix_fmt yuv420p -c:a libopus -b:a 96k -shortest sahifa-explainer.webm
   ```

   The WebM is for browsers without H.264 (open-source Chromium builds). The poster is frame 1116
   (37.2 s) scaled to 1280 wide; the captions (`sahifa-explainer.en.vtt`) follow the sentences of
   `narration.md` at the times above.

The numbers on screen are example data, the same as on the product page.
