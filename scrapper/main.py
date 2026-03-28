import argparse
import glob
import os
import shutil

from auth import load_bucket_names, load_cses_credentials, load_supabase_credentials, load_scraper_user_id
from browser import create_browser, download_tests_zip, login_cses
from problem import build_tests_url, parse_problem_text, scrape_problem_record, scrape_problem_urls
from supabase import (
	insert_problem_to_db, 
	insert_problem_sample_to_db, insert_test_case_set_to_db, insert_problem_tags_to_db, upload_text_file
)
from testcases import build_testcase_artifacts, collect_testcase_pairs, extract_zip_testcases
from utils import DOWNLOADS_DIR, ensure_dir, slugify, write_json_file, load_tags_from_json



DEFAULT_PROBLEM_TEXT = """Problem Weird Algorithm,
Time limit: 1.00 s
Memory limit: 512 MB

Consider an algorithm that takes as input a positive integer n. If n is even, the algorithm divides it by two, and if n is odd, the algorithm multiplies it by three and adds one. The algorithm repeats this, until n is one. For example, the sequence for n=3 is as follows:
$$ 3 -> 10 -> 5 -> 16 -> 8 -> 4 -> 2 -> 1$$
Your task is to simulate the execution of the algorithm for a given value of n.
Input
The only input line contains an integer n.
Output
Print a line that contains all values of n during the algorithm.
Constraints

1 <= n <= 10^6

Example
Input:
3

Output:
3 10 5 16 8 4 2 1

Tags
Show Problem Tags
Control flow
"""


def cleanup_local_downloads():
	for entry in glob.glob(os.path.join(DOWNLOADS_DIR, "*")):
		if os.path.isdir(entry):
			shutil.rmtree(entry, ignore_errors=True)
			continue
		try:
			os.remove(entry)
		except OSError:
			pass


def save_problem_record(problem, upload, problems_bucket, testcases_bucket, testcase_pairs=None, keep_local=False, created_by=""):
	problem_slug = f"{problem.task_id}-{slugify(problem.title)}" if problem.task_id else problem.slug

	problem_payload = problem.to_dict()
	testcase_pairs = testcase_pairs or []
	
	# Load and add tags from tags.json if task_id exists
	if problem.task_id:
		json_tags = load_tags_from_json(problem.task_id)
		if json_tags:
			problem_payload["tags"] = json_tags
			print(f"Added tags: {json_tags}")
	
	if not testcase_pairs:
		testcase_paths = build_testcase_artifacts(
			base_dir=DOWNLOADS_DIR,
			slug=problem_slug,
			sample_input=problem.example_input,
			sample_output=problem.example_output,
		)
		testcase_pairs = [
			{
				"index": "sample",
				"input_path": testcase_paths["input_path"],
				"output_path": testcase_paths["output_path"],
			}
		]

	if keep_local:
		json_abs_path = os.path.join(DOWNLOADS_DIR, "problems", f"{problem_slug}.json")
		write_json_file(json_abs_path, problem_payload)
		print(f"Saved problem JSON: {json_abs_path}")
	else:
		print(f"Prepared problem for database insert: {problem_slug}")
	print(f"Prepared testcase pairs: {len(testcase_pairs)}")

	if not upload:
		return

	supabase_url, supabase_key = load_supabase_credentials()
	
	# Insert problem into database
	print("Inserting problem into database...")
	problem_record = insert_problem_to_db(
		supabase_url=supabase_url,
		supabase_key=supabase_key,
		problem_data=problem_payload,
		created_by=created_by,
	)
	problem_id = problem_record.get("id")
	print(f"✓ Problem inserted with ID: {problem_id}")
	
	# Insert sample testcase into problem_samples table
	if problem.example_input and problem.example_output:
		print("Inserting sample into database...")
		insert_problem_sample_to_db(
			supabase_url=supabase_url,
			supabase_key=supabase_key,
			problem_id=problem_id,
			sample_index=1,
			input_text=problem.example_input,
			output_text=problem.example_output,
		)
		print(f"✓ Sample inserted")
	
	# Upload testcase files and create references in database
	for pair in testcase_pairs:
		with open(pair["input_path"], "r", encoding="utf-8") as handle:
			input_text = handle.read()
		with open(pair["output_path"], "r", encoding="utf-8") as handle:
			output_text = handle.read()

		# Upload to storage
		input_obj_path = f"{problem_slug}/{pair['index']}-input.txt"
		output_obj_path = f"{problem_slug}/{pair['index']}-output.txt"
		
		upload_text_file(
			supabase_url=supabase_url,
			supabase_key=supabase_key,
			bucket=testcases_bucket,
			object_path=input_obj_path,
			text=input_text,
		)
		upload_text_file(
			supabase_url=supabase_url,
			supabase_key=supabase_key,
			bucket=testcases_bucket,
			object_path=output_obj_path,
			text=output_text,
		)
		
		# Create database reference
		insert_test_case_set_to_db(
			supabase_url=supabase_url,
			supabase_key=supabase_key,
			problem_id=problem_id,
			storage_bucket=testcases_bucket,
			input_path=input_obj_path,
			output_path=output_obj_path,
		)

	# Insert tags
	if problem_payload.get("tags"):
		print("Inserting tags into database...")
		insert_problem_tags_to_db(
			supabase_url=supabase_url,
			supabase_key=supabase_key,
			problem_id=problem_id,
			tags=problem_payload["tags"],
		)
		print(f"✓ Tags linked to problem")

	print(f"✓ Problem fully inserted into database with testcases and tags")


def scrape_tests_for_problem(driver, problem):
	tests_url = build_tests_url(problem.task_id)
	if not tests_url:
		return []

	problem_slug = f"{problem.task_id}-{slugify(problem.title)}" if problem.task_id else problem.slug
	test_zip = download_tests_zip(driver, tests_url, download_dir=DOWNLOADS_DIR)
	extracted_files = extract_zip_testcases(
		zip_path=test_zip,
		base_dir=DOWNLOADS_DIR,
		folder_name=problem_slug,
	)
	return collect_testcase_pairs(extracted_files)


def main():
	default_problems_bucket, default_testcases_bucket = load_bucket_names()
	
	# Load scraper user ID from environment
	try:
		default_created_by = load_scraper_user_id()
	except ValueError as e:
		print(f"Warning: {e}")
		default_created_by = ""
	
	parser = argparse.ArgumentParser(description="CSES scraper to Supabase database")
	parser.add_argument("--problem-url", default="", help="CSES problem URL to scrape with Selenium")
	parser.add_argument("--problem-list-url", default="https://cses.fi/problemset/list/", help="CSES problem list URL")
	parser.add_argument("--tests-url", default="", help="CSES tests URL (if omitted, derived from task id)")
	parser.add_argument("--all-problems", action="store_true", help="Scrape all problems from the problem list page")
	parser.add_argument("--limit", type=int, default=0, help="Limit number of problems when using --all-problems")
	parser.add_argument("--raw-text-file", default="", help="Path to text file containing problem content")
	parser.add_argument("--cses-username", default="", help="CSES username (defaults to CSES_USERNAME env)")
	parser.add_argument("--cses-password", default="", help="CSES password (defaults to CSES_PASSWORD env)")
	parser.add_argument("--prompt-password", action="store_true", help="Prompt for CSES password if username is available")
	parser.add_argument("--upload", action="store_true", help="Upload generated artifacts to Supabase")
	parser.add_argument("--created-by", default=default_created_by, help="Clerk user ID for created_by field (loaded from SCRAPER_CLERK_USER_ID env)")
	parser.add_argument("--problems-bucket", default=default_problems_bucket, help="Supabase bucket for JSON problem files")
	parser.add_argument("--testcases-bucket", default=default_testcases_bucket, help="Supabase bucket for testcase files")
	parser.add_argument("--headless", action="store_true", help="Run Selenium browser in headless mode")
	parser.add_argument("--tag-wait-seconds", type=int, default=6, help="Wait time before reading tags on each problem page")
	parser.add_argument("--debug-tags", action="store_true", help="Print tag container diagnostics while scraping")
	parser.add_argument("--keep-local", action="store_true", help="Keep local files in scrapper/downloads after processing")
	args = parser.parse_args()
	testcase_pairs = []


	if args.raw_text_file:
		with open(args.raw_text_file, "r", encoding="utf-8") as handle:
			raw_text = handle.read()
		source_url = ""
		problem = parse_problem_text(raw_text, source_url=source_url)
		save_problem_record(
			problem=problem,
			upload=args.upload,
			problems_bucket=args.problems_bucket,
			testcases_bucket=args.testcases_bucket,
			testcase_pairs=testcase_pairs,
			keep_local=args.keep_local,
			created_by=args.created_by,
		)
		if not args.keep_local:
			cleanup_local_downloads()
		return
	elif args.all_problems:
		cses_username, cses_password = load_cses_credentials(
			username_arg=args.cses_username,
			password_arg=args.cses_password,
			prompt_if_missing=args.prompt_password,
		)
		driver = create_browser(
			headless=args.headless,
			download_dir=DOWNLOADS_DIR,
		)
		try:
			login_cses(driver, cses_username, cses_password)
			problem_urls = scrape_problem_urls(driver, args.problem_list_url)
			if args.limit > 0:
				problem_urls = problem_urls[: args.limit]

			print(f"Found problems: {len(problem_urls)}")
			for index, problem_url in enumerate(problem_urls, start=1):
				print(f"[{index}/{len(problem_urls)}] Scraping: {problem_url}")
				try:
					problem = scrape_problem_record(
						driver,
						problem_url,
						tag_wait_seconds=args.tag_wait_seconds,
						debug_tags=args.debug_tags,
					)
					pairs = scrape_tests_for_problem(driver, problem)
				except Exception as exc:
					print(f"Skipping {problem_url} due to error: {exc}")
					continue

				save_problem_record(
					problem=problem,
					upload=args.upload,
					problems_bucket=args.problems_bucket,
					testcases_bucket=args.testcases_bucket,
					testcase_pairs=pairs,
					keep_local=args.keep_local,
					created_by=args.created_by,
				)
				if not args.keep_local:
					cleanup_local_downloads()
		finally:
			driver.quit()
		return
	elif args.problem_url:
		cses_username, cses_password = load_cses_credentials(
			username_arg=args.cses_username,
			password_arg=args.cses_password,
			prompt_if_missing=args.prompt_password,
		)

		driver = create_browser(
			headless=args.headless,
			download_dir=DOWNLOADS_DIR,
		)
		try:
			login_cses(driver, cses_username, cses_password)
			problem = scrape_problem_record(
				driver,
				args.problem_url,
				tag_wait_seconds=args.tag_wait_seconds,
				debug_tags=args.debug_tags,
			)

			tests_url = args.tests_url or build_tests_url(problem.task_id)
			if tests_url:
				test_zip = download_tests_zip(driver, tests_url, download_dir=DOWNLOADS_DIR)
				extracted_files = extract_zip_testcases(
					zip_path=test_zip,
					base_dir=DOWNLOADS_DIR,
					folder_name=f"{problem.task_id}-{slugify(problem.title)}",
				)
				testcase_pairs = collect_testcase_pairs(extracted_files)
		finally:
			driver.quit()

		save_problem_record(
			problem=problem,
			upload=args.upload,
			problems_bucket=args.problems_bucket,
			testcases_bucket=args.testcases_bucket,
			testcase_pairs=testcase_pairs,
			keep_local=args.keep_local,
			created_by=args.created_by,
		)
		if not args.keep_local:
			cleanup_local_downloads()
		return
	else:
		raw_text = DEFAULT_PROBLEM_TEXT
		source_url = ""
		problem = parse_problem_text(raw_text, source_url=source_url)
		save_problem_record(
			problem=problem,
			upload=args.upload,
			problems_bucket=args.problems_bucket,
			testcases_bucket=args.testcases_bucket,
			testcase_pairs=testcase_pairs,
			keep_local=args.keep_local,
			created_by=args.created_by,
		)
		if not args.keep_local:
			cleanup_local_downloads()
		return


if __name__ == "__main__":
	main()
