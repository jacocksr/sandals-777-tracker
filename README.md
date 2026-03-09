# 7·7·7 Watch — Sandals Deal Tracker

An independent, automated tracker for Sandals Resorts' weekly 7-7-7 promotion.

---

## How It Works (plain English)

1. **Every Wednesday**, GitHub (a free code storage website) automatically runs a Python script on its servers.
2. That script opens an invisible Chrome browser, loads the Sandals 7-7-7 page, reads the deals, and saves them to `data/deals.json`.
3. Your website (a single HTML file) reads `deals.json` and displays the deals beautifully.
4. Visitors see live, current data — updated automatically, every week, for free.

**Cost to run: $0/month** using GitHub Pages + GitHub Actions free tier.

---

## Project Structure

```
sandals-tracker/
├── .github/
│   └── workflows/
│       └── scrape-weekly.yml   ← Automated weekly scheduler
├── data/
│   ├── deals.json              ← This week's deals (auto-updated)
│   └── history.json            ← Every week ever scraped (grows over time)
├── scripts/
│   └── scraper.py              ← The Python scraper
├── site/
│   └── index.html              ← Your website
└── README.md                   ← This file
```

---

## Step-by-Step: Get This Live in 30 Minutes

### Step 1 — Create a GitHub Account

1. Go to [github.com](https://github.com) and click **Sign up** (top right)
2. Choose a username, enter your email, create a password
3. Verify your email when they send you a confirmation

### Step 2 — Create a New Repository

A "repository" (or "repo") is just a folder on GitHub that stores your code.

1. Once logged in, click the **+** icon (top right) → **New repository**
2. Repository name: `sandals-777-tracker` (or anything you like)
3. Set it to **Public** (required for free hosting)
4. Check **Add a README file**
5. Click **Create repository**

### Step 3 — Upload Your Files

1. On your new repository page, click **Add file** → **Upload files**
2. Upload everything from this project folder, keeping the folder structure:
   - Drag the `.github` folder
   - Drag the `data` folder
   - Drag the `scripts` folder
   - Drag the `site` folder
3. At the bottom, click **Commit changes**

> **Tip on the .github folder:** On Mac, folders starting with `.` are hidden by default. Press `Cmd+Shift+.` in Finder to show hidden files before uploading.

### Step 4 — Enable GitHub Pages (Free Hosting)

GitHub Pages turns your repository into a live website automatically.

1. In your repository, click **Settings** (tab near the top)
2. In the left sidebar, click **Pages**
3. Under "Source", select **Deploy from a branch**
4. Under "Branch", select **main** and set the folder to **/site**
5. Click **Save**
6. Wait 1-2 minutes, then your site will be live at:
   `https://YOUR-USERNAME.github.io/sandals-777-tracker`

### Step 5 — Verify the Scraper Works

1. In your repository, click the **Actions** tab
2. On the left, click **"Scrape Sandals 7·7·7 Deals"**
3. Click **Run workflow** → **Run workflow** (green button)
4. Watch it run! It takes about 2-3 minutes.
5. If it shows a green checkmark ✅ — everything works!
6. If it shows a red ✗ — click on it to see the error log

> The scraper will now run automatically every Wednesday at 6am UTC (1am US Eastern).

---

## Troubleshooting

### "The site shows old/fallback data"
- The site reads `data/deals.json`. If the scraper hasn't run yet, you'll see the seed data.
- Manually trigger the scraper via the Actions tab.

### "The scraper failed with a Timeout error"
- Sandals' website was slow or down. Try running manually again.
- If it keeps failing, Sandals may have updated their page structure. Open an issue.

### "I see a CORS error in the browser console"
- This happens when you open `index.html` directly from your computer (the `file://` protocol).
- The site works correctly when hosted on GitHub Pages.
- To test locally, run a simple server: `python3 -m http.server 8000` inside the `site/` folder, then visit `http://localhost:8000`.

### "The scraper extracted 0 deals"
- Sandals may have updated their page's HTML structure.
- Open `scripts/scraper.py` and update the `CARD_SELECTORS` list with the new CSS selectors.
- You can find these by right-clicking a deal card on their site → Inspect Element.

---

## Customizing the Site

- **Colors/fonts:** Edit the `:root` CSS variables at the top of `site/index.html`
- **Adding a custom domain:** In GitHub Pages Settings, add a custom domain (e.g. `777deals.com`) — you'll need to buy the domain (~$12/year) and point its DNS to GitHub
- **Email alerts:** Sign up for [EmailOctopus](https://emailoctopus.com) (free up to 2,500 subscribers) and replace the `subscribeAlert()` function with their embed code

---

## Legal Notes

- This site is an **independent tracker** and is not affiliated with Sandals Resorts International.
- Deal data is sourced from Sandals' public website.
- Always verify pricing and availability at [sandals.com](https://www.sandals.com/specials/suite-deals/) before booking.
- Prices shown are for informational purposes only.

---

## Future Ideas

- [ ] Price history charts per room code
- [ ] "Notify me when resort X appears" alerts
- [ ] Affiliate link integration for commission on bookings
- [ ] Twitter/X bot that tweets the deals every Wednesday
- [ ] Compare total discount % across weeks

---

*Built for travelers, by travelers.*
