# CSES Scraper -> Supabase Database

This project scrapes CSES problem content and inserts it directly into a Supabase PostgreSQL database:

- **problems** table: Problem metadata with difficulty, time/memory limits, tags
- **problem_samples** table: Example inputs/outputs shown on problem pages
- **problem_tags** table: Tags linked to problems from prebuilt `tags.json`
- **test_case_sets** table: References to testcase files stored in Supabase Storage

## Features

- ✅ Scrapes problem statements from CSES
- ✅ Automatically downloads test cases (if available)
- ✅ Adds tags from prebuilt `tags.json` (no browser extension needed)
- ✅ **Inserts directly into PostgreSQL database** (no JSON file uploads)
- ✅ Stores testcase files in Supabase Storage
- ✅ Supports batch processing of all problems
- ✅ Environment-based configuration

## Install

```powershell
python -m pip install -r requirements.txt
```

## Setup Tags

The scraper uses prebuilt tags from `scrapper/tags.json`. This file should contain a mapping of problem IDs to tag arrays:

```json
{
  "1068": ["Control flow"],
  "1083": ["Control flow", "Math"],
  "1071": ["Math", "Geometry"]
}
```

To collect all unique tags from your tags.json:

```powershell
python "scrapper/collect_tags.py"
```

This creates `all-tags.txt` with all sorted unique tags.

## Run (local files only)

```powershell
python "scrapper/main.py"
```

This uses the built-in Weird Algorithm sample problem.

## Run with a text file

```powershell
python "scrapper/main.py" --raw-text-file "C:\path\to\problem.txt"
```

## Run with a live CSES URL and upload to database

```powershell
python "scrapper/main.py" --problem-url "https://cses.fi/problemset/task/1068" --upload
```

Tags are automatically loaded from `tags.json` and linked in the database if a matching task ID exists.

With test cases:

```powershell
python "scrapper/main.py" --problem-url "https://cses.fi/problemset/task/1068" --tests-url "https://cses.fi/problemset/tests/1068/" --upload
```

## CSES Credentials

Supported via environment variables or CLI arguments:

- `CSES_USERNAME` / `--cses-username`
- `CSES_PASSWORD` / `--cses-password`
- `--prompt-password` to be prompted interactively

## Scrape all problems and insert to database

```powershell
python "scrapper/main.py" --all-problems --upload
```

With limit for testing:

```powershell
python "scrapper/main.py" --all-problems --limit 10 --upload
```

## Upload to Supabase

The scraper auto-loads `.env` from project root or `scrapper/.env` if present.

Supported environment variables:

```env
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
SUPABASE_STORAGE_TESTCASES_BUCKET=testcases
```

Or use shell environment variables:

```powershell
$env:SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
$env:SUPABASE_SERVICE_ROLE_KEY = "YOUR_SERVICE_ROLE_KEY"
```

Then run with `--upload` flag:

```powershell
python "scrapper/main.py" --all-problems --upload
```

## Database Insertion Flow

When `--upload` is used:

1. **Problems table**: Insert problem metadata (title, slug, description, limits, etc.)
2. **Problem samples**: Insert example input/output from problem page
3. **Test case sets**: Create storage references for all downloaded testcases
4. **Problem tags**: Link tags from `tags.json` to the problem
5. **Storage**: Upload testcase files to Supabase Storage

## Local File Retention

By default, files are NOT saved locally and are inserted directly to the database.

To keep local copies in `scrapper/downloads/`:

```powershell
python "scrapper/main.py" --all-problems --upload --keep-local
```

## Helper Scripts

### List Recent Problems

View problems already inserted in the database:

```powershell
python "scrapper/list_problems.py"
```

### List Available Users

View users in the database:

```powershell
python "scrapper/list_users.py"
```

### Verify Insertion

Verify that a problem was correctly inserted with all related data:

```powershell
python "scrapper/verify_insert.py"
```

(Edit the script to change the slug being verified)

## Complete Example

Scrape problem 1068 with testcases, add tags from tags.json, and insert to database:

```powershell
python "scrapper/main.py" \
  --problem-url "https://cses.fi/problemset/task/1068" \
  --tests-url "https://cses.fi/problemset/tests/1068/" \
  --cses-username "your_username" \
  --cses-password "your_password" \
  --upload
```

## Database Schema

The scraper works with these tables:

- **problems**: Core problem metadata
- **problem_samples**: Example inputs/outputs  
- **problem_tags** (junction): Links problems to tags
- **tags**: Available tags
- **test_case_sets**: References to testcase files in storage
- **user_profiles**: Users who created problems (required for `created_by` foreign key)

## Architecture

The scraper uses:

- **Selenium + Chrome**: Automates CSES website navigation and testcase download
- **BeautifulSoup (via Selenium)**: Parses problem statements from HTML
- **tags.json**: Provides prebuilt tags for each problem
- **Supabase PostgREST API**: Inserts data directly into PostgreSQL
- **Supabase Storage**: Uploads testcase files









