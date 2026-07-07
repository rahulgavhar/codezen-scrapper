# 🚀 Codezen Data Ingestion Pipeline (CSES Scraper)

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![Supabase](https://img.shields.io/badge/Supabase-Database-3ECF8E?logo=supabase)](https://supabase.com)
[![Selenium](https://img.shields.io/badge/Selenium-Web%20Scraping-43B02A?logo=selenium)](https://www.selenium.dev/)
[![Architecture](https://img.shields.io/badge/Architecture-Data%20Pipeline-ff69b4.svg)]()

> **Note to Interviewers:** This document provides a high-level architectural overview of the Codezen Scraper project, detailing the engineering decisions, system design, and challenges overcome during its development.

## 🎯 Project Overview

The **Codezen Data Ingestion Pipeline** is an automated ETL (Extract, Transform, Load) system designed to scrape algorithmic coding problems from the CSES Problem Set and seamlessly ingest them into a structured [Supabase](https://supabase.com/) PostgreSQL database and Storage buckets.

The core motivation behind this project was to automate the highly manual process of migrating competitive programming problems (including complex Markdown statements, KaTeX math formulas, constraints, and zipped test cases) into a modern relational database to power a centralized coding platform.

## 🏗 Architecture & Tech Stack

The project is built using a modular, decoupled architecture to ensure scalability and maintainability.

- **Data Extraction (Web Automation):** `Selenium WebDriver` (Python)
  - *Why Selenium?* CSES problems often involve dynamic content, bot-protection, and file downloads (e.g., zipped test cases). Selenium running in a headless Chrome environment provided the robustness needed to mimic real user interactions and intercept file downloads reliably.
- **Data Transformation:** Python `re`, `dataclasses`, and DOM Parsing
  - *Why Custom Parsing?* Algorithmic problems have deeply nested structures (e.g., separating "Input", "Output", and "Constraints" while preserving HTML `KaTeX` tags for math rendering).
- **Data Loading (Database & Storage):** `Supabase PostgREST API`
  - *Why Supabase?* It provided a rapid backend-as-a-service solution. Instead of writing raw SQL or managing an ORM, the pipeline leverages Supabase's REST APIs to handle relational data insertion (handling foreign keys) and blob storage directly.

## 🔄 Data Ingestion Pipeline (ETL Flow)

The ETL workflow operates in a single, resilient pass:

1. **Extraction (Web Scraping):** 
   - Authenticates with the CSES portal.
   - Navigates through the problem list or targets specific URLs.
   - Intercepts and downloads `.zip` archives containing hidden test case artifacts.
2. **Transformation (Data Cleaning):**
   - Extracts rich text and isolates math formulas from standard paragraphs.
   - Unzips test cases and pairs `.in` and `.out` file equivalents programmatically.
   - Enriches problem data with contextual tags from a pre-built static `tags.json` dictionary.
3. **Loading (Database Transaction):**
   - Uploads raw testcase `.txt` artifacts into **Supabase Storage**.
   - Inserts core problem metadata into the `problems` table.
   - Inserts problem samples (examples shown to the user) into `problem_samples`.
   - Populates junction tables (`problem_tags`, `test_case_sets`) to maintain strict referential integrity.

## 🗄 Database Schema Design

The system maps scraped unstructured data into a highly relational PostgreSQL schema designed for fast querying by the frontend client:

- **`problems`**: The core entity storing time limits, memory limits, calculated difficulty, and sanitized rich text.
- **`problem_samples`**: A 1-to-many relationship linking problems to visible input/output examples.
- **`tags` & `problem_tags`**: A many-to-many junction schema categorizing problems (e.g., "Dynamic Programming", "Graph Theory").
- **`test_case_sets`**: Links problem records to the exact S3/Supabase Storage URIs containing the hidden evaluation files.
- **`user_profiles`**: Tracks the ingestion source and authorization (Foreign key: `created_by`).

## 🚧 Key Challenges & Engineering Solutions

1. **Preserving Mathematical Formulas (KaTeX)**
   - *Challenge:* Standard text extraction strips out HTML nodes, destroying complex mathematical equations crucial for coding problems.
   - *Solution:* Implemented a custom JavaScript execution script within Selenium (`_extract_section_html`) that traverses DOM nodes to isolate and preserve raw HTML structures for specific sections (Input, Output, Constraints) while stripping generic text.
2. **Robust File Downloading in Headless Environments**
   - *Challenge:* Headless Chrome notoriously struggles with automated file downloads without explicit user-prompt interactions.
   - *Solution:* Overrode Chrome DevTools Protocol (CDP) commands (`Page.setDownloadBehavior`) programmatically to force automated background downloading into a temporary OS-level directory. Implemented polling mechanisms to ensure zip files were fully constructed before proceeding.
3. **Network Resilience & Rate Limiting**
   - *Challenge:* Mass-uploading thousands of text files and JSON payloads to Supabase could trigger rate limits or drop packets.
   - *Solution:* Implemented exponential backoff and retry logic at the HTTP request layer to gracefully handle `429 Too Many Requests` and transient network errors during the loading phase.

## 🕸 Deep Dive: Advanced Selenium Usage

A critical component of this ingestion pipeline is the highly customized `Selenium WebDriver` implementation used to automate interactions with the CSES portal. Standard web scraping libraries (like `requests` or `BeautifulSoup`) were insufficient due to dynamic content rendering, session-based authentication, and hidden file downloads. 

Here is a detailed breakdown of the advanced Selenium techniques utilized:

### 1. Headless Chrome with DevTools Protocol (CDP)
Running a browser in a headless environment (e.g., CI/CD pipelines or cloud servers) typically blocks automated file downloads for security reasons. To bypass this restriction, the scraper directly leverages the **Chrome DevTools Protocol (CDP)**:
- We execute `Page.setDownloadBehavior` via `driver.execute_cdp_cmd()` to force Chrome to allow downloads.
- We explicitly map the `downloadPath` to a temporary OS-level directory (`/downloads`), ensuring that zipped test cases are saved consistently without triggering native OS save dialogs.

### 2. WebDriver BiDi & Extension Management
To handle dynamic tag injection natively within the browser context, the scraper supports loading unpacked extensions or `.crx` files at runtime. It modernizes this approach by attempting to use the new **WebDriver BiDi** protocol (`driver.install_addon()`). If BiDi is unsupported, it gracefully falls back to legacy command-line argument loading (`--load-extension`).

### 3. Asynchronous DOM Polling (Custom Waiters)
Instead of relying on brittle static `time.sleep()` calls, the scraper uses `WebDriverWait` combined with custom lambda functions to poll the DOM dynamically. 
- During login (`login_cses`), it polls for multiple permutations of CSS selectors (`[name='nick']`, `[name='username']`, etc.) to resiliently handle UI changes.
- For zip file downloads (`_wait_for_zip`), it continuously polls the local OS file system to verify file sizes and wait until the `.crdownload` (Chrome's temporary download extension) disappears, guaranteeing file integrity before the ETL pipeline proceeds.

### 4. JavaScript Execution for Context-Aware Parsing
Extracting mathematical formulas (KaTeX) from competitive programming platforms is notoriously difficult because text extractors strip out HTML rendering tags. 
- The scraper bypasses standard Selenium `.text` extraction.
- Instead, it injects a custom JavaScript payload (`driver.execute_script()`) that iterates over DOM nodes (`root.children`), categorizing them into distinct problem sections ("Input", "Output", "Constraints").
- It captures the `outerHTML` of these nodes, ensuring that complex structural elements (like bold tags and `span.katex`) are preserved perfectly for the database, allowing 1:1 rendering on the target platform.

## 🚀 Future Scalability

While currently functioning as a CLI orchestration tool, the architecture is designed to be easily containerized (Docker) and scaled horizontally using message queues (e.g., Celery/RabbitMQ) or serverless functions (AWS Lambda/GCP Cloud Run) if the ingestion source pool expands beyond CSES.

---

## 💻 Developer Setup & Usage Guide

If you are a developer looking to run, extend, or test the scraper locally, follow the instructions below.

### 1️⃣ Installation

Install the required Python packages (we recommend using a virtual environment):
```powershell
python -m pip install -r requirements.txt
```

### 2️⃣ Environment Configuration

The scraper automatically loads variables from a `.env` file located in the project root or the `scrapper/` directory.

**Required Supabase Variables:**
```env
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
SUPABASE_STORAGE_TESTCASES_BUCKET=testcases
```
*(Alternatively, set these directly in your PowerShell session: `$env:SUPABASE_URL = "..."`)*

**CSES Credentials:**
You can supply these via `.env` or pass them explicitly via CLI arguments:
- `CSES_USERNAME` / `--cses-username`
- `CSES_PASSWORD` / `--cses-password`
- Use `--prompt-password` for interactive, secure prompting.

### 3️⃣ Setting Up Tags

The scraper uses a pre-built static mapping found in `scrapper/tags.json` to link problem IDs to their respective tags (avoiding the need for external browser extensions during scraping).

**Example `tags.json` structure:**
```json
{
  "1068": ["Control flow"],
  "1083": ["Control flow", "Math"],
  "1071": ["Math", "Geometry"]
}
```
To aggregate and verify all unique tags available in your JSON file, run:
```powershell
python scrapper/collect_tags.py
```
*(This generates an `all-tags.txt` file with sorted tag data).*

### 4️⃣ Execution Commands

You can execute `main.py` using various strategies depending on your ingestion needs:

**A. Local Mock Run (No Network):**
Processes a built-in "Weird Algorithm" text stub. Great for testing the parsing engine.
```powershell
python scrapper/main.py
```

**B. Process a Local Text File:**
```powershell
python scrapper/main.py --raw-text-file "C:\path\to\problem.txt"
```

**C. Scrape a Single Live CSES Problem & Upload:**
```powershell
python scrapper/main.py --problem-url "https://cses.fi/problemset/task/1068" --upload
```
*To also download and upload hidden test cases, provide the tests URL:*
```powershell
python scrapper/main.py \
  --problem-url "https://cses.fi/problemset/task/1068" \
  --tests-url "https://cses.fi/problemset/tests/1068/" \
  --upload
```

**D. Batch Processing (All Problems):**
```powershell
python scrapper/main.py --all-problems --upload
```
*(Tip: Use `--limit 10` for testing, or `--offset 50` to resume a broken pipeline).*

**E. Local File Retention:**
By default, files are held in memory/temp and discarded after database insertion. To keep physical copies of the JSON payloads and ZIP files in `scrapper/downloads/`:
```powershell
python scrapper/main.py --all-problems --upload --keep-local
```

### 🧰 Helper Utilities

The repository includes standalone scripts for database verification and management:

- **View recently inserted problems:**
  ```powershell
  python scrapper/list_problems.py
  ```
- **List authorized user profiles:**
  ```powershell
  python scrapper/list_users.py
  ```
- **Verify full data integrity for a specific problem:**
  ```powershell
  python scrapper/verify_insert.py
  ```
  *(Edit the script directly to target a specific problem slug for verification).*
