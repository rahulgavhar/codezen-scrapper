import datetime as dt
import re
import time
from dataclasses import dataclass, field

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from utils import slugify


CSES_BASE_URL = "https://cses.fi"


def _normalize_tag_values(values):
	cleaned = []
	seen = set()
	for value in values:
		text = (value or "").strip()
		if not text:
			continue
		if len(text) > 60:
			continue
		if text.lower() in {"tags", "show problem tags", "tips", "no tips", "your submissions", "..."}:
			continue
		if re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}$", text):
			continue
		if text in seen:
			continue
		seen.add(text)
		cleaned.append(text)
	return cleaned


def extract_tags_from_page(driver, problem_title=""):
	values = []

	# Primary path: extension-injected tags container, e.g. #tags-container > details#show-tags > ul#tags > li
	for selector in [
		"#tags-container #tags li",
		"details#show-tags ul#tags li",
		"ul#tags li",
	]:
		for element in driver.find_elements(By.CSS_SELECTOR, selector):
			values.append(element.text)
	if values:
		return _normalize_tag_values(values)

	# Parse only the main content area around the extension-injected Tags block.
	content = driver.find_element(By.CSS_SELECTOR, "div.content")
	lines = [line.strip() for line in content.text.splitlines()]
	stop_tokens = {
		"tips",
		"no tips",
		"your submissions",
		"input",
		"output",
		"constraints",
		"example",
	}

	if "Show Problem Tags" in lines:
		start = lines.index("Show Problem Tags") + 1
		for line in lines[start : start + 12]:
			if not line:
				if values:
					break
				continue
			if line.lower() in stop_tokens:
				break
			if problem_title and line.lower() == problem_title.lower():
				break
			if len(values) >= 5:
				break
			values.append(line)
	elif "Tags" in lines:
		start = lines.index("Tags") + 1
		for line in lines[start : start + 12]:
			if not line:
				if values:
					break
				continue
			if line.lower() in stop_tokens or line.lower() == "show problem tags":
				continue
			if problem_title and line.lower() == problem_title.lower():
				break
			if len(values) >= 5:
				break
			values.append(line)

	return _normalize_tag_values(values)


def wait_for_extension_tags(driver, timeout_seconds):
	if timeout_seconds <= 0:
		return

	try:
		WebDriverWait(driver, timeout_seconds).until(
			lambda d: len(d.find_elements(By.CSS_SELECTOR, "#tags-container #tags li")) > 0
		)
		return
	except TimeoutException:
		pass

	# Fallback: if tags were not injected, preserve previous behavior with a bounded wait.
	time.sleep(timeout_seconds)


@dataclass
class ProblemRecord:
	task_id: str
	title: str
	time_limit: str
	memory_limit: str
	statement: str
	input_description: str
	output_description: str
	constraints: list[str] = field(default_factory=list)
	example_input: str = ""
	example_output: str = ""
	tags: list[str] = field(default_factory=list)
	source_url: str = ""
	slug: str = ""

	def to_dict(self):
		constraints_text = "\n".join(self.constraints) if self.constraints else ""
		return {
			"id": self.slug,
			"task_id": self.task_id,
			"url": self.source_url,
			"title": self.title,
			"time_limit": self.time_limit,
			"memory_limit": self.memory_limit,
			"statement_text": self.statement,
			"input_section": self.input_description,
			"output_section": self.output_description,
			"constraints": self.constraints,
			"constraints_text": constraints_text,
			"example": {
				"input": self.example_input,
				"output": self.example_output,
			},
			"tags": self.tags,
			"scraped_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
		}


def scrape_problem_text(driver, problem_url):
	driver.get(problem_url)


def scrape_problem_urls(driver, list_url=f"{CSES_BASE_URL}/problemset/list/"):
	driver.get(list_url)
	anchors = driver.find_elements(By.CSS_SELECTOR, "ul.task-list li.task a[href*='/problemset/task/']")
	seen = set()
	urls = []
	for anchor in anchors:
		href = (anchor.get_attribute("href") or "").strip()
		if not href:
			continue
		if href in seen:
			continue
		seen.add(href)
		urls.append(href)
	return urls


def scrape_problem_record(driver, problem_url, tag_wait_seconds=0, debug_tags=False):
	driver.get(problem_url)

	show_tags_candidates = driver.find_elements(
		By.XPATH,
		"//*[self::a or self::button or self::span][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'show problem tags')]",
	)
	if show_tags_candidates:
		try:
			show_tags_candidates[0].click()
		except Exception:
			pass

	if tag_wait_seconds > 0:
		# Some pages render tags asynchronously after initial load.
		time.sleep(tag_wait_seconds)

	title = ""
	for selector in ["div.navigation .title-block h1", "h1"]:
		matches = driver.find_elements(By.CSS_SELECTOR, selector)
		if matches:
			title = matches[0].text.strip()
			break
	if not title:
		raise ValueError(f"Could not find problem title on page: {problem_url}")

	time_limit = ""
	memory_limit = ""
	for item in driver.find_elements(By.CSS_SELECTOR, "ul.task-constraints li"):
		text = item.text.strip()
		if text.lower().startswith("time limit:"):
			time_limit = text.split(":", 1)[1].strip()
		elif text.lower().startswith("memory limit:"):
			memory_limit = text.split(":", 1)[1].strip()

	md_blocks = driver.find_elements(By.CSS_SELECTOR, "div.content .md")
	if not md_blocks:
		raise ValueError(f"Could not find problem body (.md) on page: {problem_url}")
	statement_text = md_blocks[0].text

	tags = extract_tags_from_page(driver, problem_title=title)
	if debug_tags:
		tags_container_count = len(driver.find_elements(By.CSS_SELECTOR, "#tags-container"))
		tags_li_count = len(driver.find_elements(By.CSS_SELECTOR, "#tags-container #tags li"))
		print(
			f"Tag debug for {title}: containers={tags_container_count}, items={tags_li_count}, parsed={tags}"
		)

	synthetic = (
		f"Problem {title},\n"
		f"Time limit: {time_limit}\n"
		f"Memory limit: {memory_limit}\n\n"
		f"{statement_text}"
	)
	record = parse_problem_text(synthetic, source_url=problem_url)
	if tags:
		record.tags = tags
	return record


def extract_task_id_from_url(url):
	match = re.search(r"/task/(\d+)", url or "")
	return match.group(1) if match else ""


def build_tests_url(task_id):
	if not task_id:
		return ""
	return f"https://cses.fi/problemset/tests/{task_id}/"


def _section_indices(lines):
	labels = ["Input", "Output", "Constraints", "Example", "Tags"]
	indices = {}
	for idx, line in enumerate(lines):
		if line in labels and line not in indices:
			indices[line] = idx
	return indices


def _clean_block(lines):
	# Strip only edge-empty lines so internal spacing remains readable.
	start = 0
	end = len(lines)
	while start < end and not lines[start].strip():
		start += 1
	while end > start and not lines[end - 1].strip():
		end -= 1
	return "\n".join(lines[start:end]).strip()


def _extract_example(example_lines):
	example_input = ""
	example_output = ""
	input_start = None
	output_start = None
	for idx, line in enumerate(example_lines):
		if line.strip().lower().startswith("input") and input_start is None:
			input_start = idx
		if line.strip().lower().startswith("output") and output_start is None:
			output_start = idx

	if input_start is not None and output_start is not None and input_start < output_start:
		example_input = _clean_block(example_lines[input_start + 1 : output_start])
		example_output = _clean_block(example_lines[output_start + 1 :])

	return example_input, example_output


def parse_problem_text(raw_text, source_url=""):
	lines = [line.rstrip() for line in raw_text.splitlines()]

	title = ""
	time_limit = ""
	memory_limit = ""

	title_re = re.compile(r"^Problem\s+(.+?)[,\s]*$")
	time_re = re.compile(r"^Time\s+limit:\s*(.+)$", re.IGNORECASE)
	memory_re = re.compile(r"^Memory\s+limit:\s*(.+)$", re.IGNORECASE)

	for line in lines:
		stripped = line.strip()
		if not title:
			title_match = title_re.match(stripped)
			if title_match:
				title = title_match.group(1).strip()
				continue
		if not time_limit:
			time_match = time_re.match(stripped)
			if time_match:
				time_limit = time_match.group(1).strip()
				continue
		if not memory_limit:
			memory_match = memory_re.match(stripped)
			if memory_match:
				memory_limit = memory_match.group(1).strip()

	if not title:
		raise ValueError("Could not parse problem title from source text.")

	indices = _section_indices(lines)
	required_sections = ["Input", "Output", "Constraints", "Example"]
	missing = [name for name in required_sections if name not in indices]
	if missing:
		raise ValueError("Missing sections in problem text: " + ", ".join(missing))

	statement_start = 0
	for idx, line in enumerate(lines):
		if memory_re.match(line.strip()):
			statement_start = idx + 1
			break

	statement_lines = lines[statement_start : indices["Input"]]
	input_lines = lines[indices["Input"] + 1 : indices["Output"]]
	output_lines = lines[indices["Output"] + 1 : indices["Constraints"]]

	example_end = indices.get("Tags", len(lines))
	constraints_lines = lines[indices["Constraints"] + 1 : indices["Example"]]
	example_lines = lines[indices["Example"] + 1 : example_end]
	tags_lines = lines[indices["Tags"] + 1 :] if "Tags" in indices else []

	example_input, example_output = _extract_example(example_lines)
	tags = [line.strip() for line in tags_lines if line.strip() and "show problem tags" not in line.lower()]

	return ProblemRecord(
		task_id=extract_task_id_from_url(source_url),
		title=title,
		time_limit=time_limit,
		memory_limit=memory_limit,
		statement=_clean_block(statement_lines),
		input_description=_clean_block(input_lines),
		output_description=_clean_block(output_lines),
		constraints=[line.strip() for line in constraints_lines if line.strip()],
		example_input=example_input,
		example_output=example_output,
		tags=tags,
		source_url=source_url,
		slug=slugify(title),
	)











