# 🏖️ Sandals & Beaches 777 Tracker

[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Deployed-success?logo=github)](https://jacocksr.github.io/sandals-777-tracker/)
[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![Data Format](https://img.shields.io/badge/Data-JSON-lightgray.svg)]()
[![Automation](https://img.shields.io/badge/Action-Automated%20Scraping-green.svg)]()

An automated tracking system that scrapes, records, and publishes the latest discounted room deals (777 promotions) for Sandals and Beaches Resorts. 

The project uses Python to scrape weekly deals, stores the current and historical data in JSON format, and presents it through a static website hosted on GitHub Pages.

---

## ✨ Features

- **Automated Scraping**: Dedicated Python scripts extract the latest 7%+ off deals for both Sandals and Beaches resorts.
- **Data Logging**: Maintains both a current snapshot (`deals.json`) and a running historical log (`history.json`) to track price changes over time.
- **Static Web Dashboard**: A frontend hosted on GitHub Pages (`docs/` folder) allows users to easily view current deals and historical trends without looking at raw code.
- **CI/CD Integration**: Designed to be automated via GitHub Actions (`.github/workflows`) to run the scrapers on a weekly schedule.

---

## 📂 Repository Structure

```text
├── .github/                 # GitHub Actions workflows for automated scraping
├── README.md                # Project documentation
├── scripts/                 # Python scraping modules
│   ├── scraper.py           # Main scraper for Sandals 777 deals
│   └── beaches-scraper.py   # Main scraper for Beaches deals
├── docs/                    # GitHub Pages static site files
│   ├── index.html           # Frontend dashboard for Sandals deals
│   ├── beaches-index.html   # Frontend dashboard for Beaches deals
│   ├── data/                # Frontend data assets
│   └── images/              # Frontend image assets
└── *.json                   # Data output files (deals & history logs)
```

---

## 🚀 Setup & Installation

To run the scrapers locally and contribute to the project, follow these steps:

### 1. Clone the Repository
```bash
git clone https://github.com/jacocksr/sandals-777-tracker.git
cd sandals-777-tracker
```

### 2. Set Up a Virtual Environment
It's recommended to use a virtual environment to manage dependencies.
```bash
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
```

### 3. Install Dependencies
*(Note: Ensure you have a `requirements.txt` file listing your web scraping libraries such as `requests`, `beautifulsoup4`, or `selenium`)*
```bash
pip install -r requirements.txt
```

---

## 🛠️ Usage

### Running the Scrapers
To fetch the latest deals and update the JSON files, execute the scripts from the root directory:

**For Sandals Resorts:**
```bash
python scripts/scraper.py
```
*Updates `deals.json` and appends to `history.json`.*

**For Beaches Resorts:**
```bash
python scripts/beaches-scraper.py
```
*Updates `beaches-deals.json` and appends to `beaches-history.json`.*

### Viewing the Frontend Locally
Since the frontend uses basic HTML/JS, you can preview the site locally by spinning up a simple Python server:
```bash
cd docs
python -m http.server 8000
```
Then navigate to `http://localhost:8000` in your web browser.

---

## 🤖 Automation (GitHub Actions)

This project leverages GitHub Actions to run automatically. The workflows located in `.github/` are configured to:
1. Spin up a runner on a weekly cron schedule (typically Wednesdays when new 777 deals drop).
2. Execute both `scraper.py` and `beaches-scraper.py`.
3. Commit any changes to the `*.json` files back to the repository.
4. Trigger a GitHub Pages deployment to update the live dashboards.

---

## 📊 Data Structure

The output data is structured in JSON for easy integration with the frontend. A typical deal entry includes:
- **Resort Name & Location** (e.g., Sandals Saint Vincent)
- **Room Category**
- **Original Price vs. Discounted Price**
- **Travel Window Dates**
- **Booking URL**

---

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.
