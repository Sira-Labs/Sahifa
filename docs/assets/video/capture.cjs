// node capture.cjs stills 5,17.5   |   node capture.cjs frames 30 [timeline.json]
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");
(async () => {
  const [mode, arg, timeline] = process.argv.slice(2);
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  page.on("console", (m) => console.log("page:", m.text()));
  page.on("pageerror", (e) => { console.error("pageerror:", e.message); process.exit(1); });
  await page.goto("file://" + path.join(__dirname, "sahifa-explainer.html") + "?capture=1");
  await page.evaluate(() => window.ready);
  if (timeline) {
    const tl = JSON.parse(fs.readFileSync(timeline, "utf8"));
    await page.evaluate((tl) => window.setTimeline(tl.scenes, tl.duration), tl);
  }
  const grab = async (t, file, type) => {
    const data = await page.evaluate(([t, type]) => { window.render(t); return document.getElementById("c").toDataURL(type, 0.92); }, [t, type]);
    fs.writeFileSync(file, Buffer.from(data.split(",")[1], "base64"));
  };
  if (mode === "stills") {
    fs.mkdirSync(path.join(__dirname, "stills"), { recursive: true });
    for (const t of arg.split(",").map(Number)) await grab(t, path.join(__dirname, "stills", `s${String(t).padStart(5, "0")}.png`), "image/png");
  } else {
    const fps = Number(arg), dur = await page.evaluate(() => window.DURATION());
    const dir = path.join(__dirname, "frames"); fs.mkdirSync(dir, { recursive: true });
    const n = Math.round(dur * fps);
    for (let i = 0; i < n; i++) {
      await grab(i / fps, path.join(dir, `f${String(i).padStart(5, "0")}.jpg`), "image/jpeg");
      if (i % 300 === 0) console.log(`frame ${i}/${n}`);
    }
  }
  await browser.close();
})();
