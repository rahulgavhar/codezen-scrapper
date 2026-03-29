import datetime as dt
import re
import time
from dataclasses import dataclass, field

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from utils import slugify


CSES_BASE_URL = "https://cses.fi"


def categorize_difficulty(success_rate):
	"""Categorize problem difficulty based on success rate.
	
	- hard: < 75% success rate (challenging)
	- medium: 75-85% success rate (moderate challenge)
	- easy: > 85% success rate (most solve)
	"""
	if success_rate > 85:
		return "easy"
	elif success_rate >= 75:
		return "medium"
	else:
		return "hard"


def scrape_problem_stats(driver, task_id):
	"""Scrape problem stats page to extract difficulty metrics.
	
	Returns a dict with success_rate and calculated difficulty.
	"""
	if not task_id:
		return {"success_rate": 0.0, "difficulty": "medium"}
	
	stats_url = f"{CSES_BASE_URL}/problemset/stats/{task_id}/"
	try:
		driver.get(stats_url)
		time.sleep(1)
		
		# Extract success rate from summary table
		summary_rows = driver.find_elements(By.CSS_SELECTOR, "table.summary-table tr")
		success_rate = 0.0
		
		for row in summary_rows:
			cells = row.find_elements(By.CSS_SELECTOR, "td")
			if len(cells) >= 2:
				label = cells[0].text.strip()
				value = cells[1].text.strip()
				
				if "success rate" in label.lower():
					# Parse percentage (e.g., "92.56%")
					match = re.search(r"([\d.]+)", value)
					if match:
						success_rate = float(match.group(1))
					break
		
		difficulty = categorize_difficulty(success_rate)
		return {"success_rate": success_rate, "difficulty": difficulty}
	
	except Exception as e:
		print(f"Warning: Could not scrape stats for task {task_id}: {e}")
		return {"success_rate": 0.0, "difficulty": "medium"}


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
	constraints_html: str = ""
	example_input: str = ""
	example_output: str = ""
	examples: list[tuple] = field(default_factory=list)
	tags: list[str] = field(default_factory=list)
	source_url: str = ""
	slug: str = ""
	difficulty: str = "medium"

	def to_dict(self):
		constraints_text = self.constraints_html.strip() if self.constraints_html else ("\n".join(self.constraints) if self.constraints else "")
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
			"difficulty": self.difficulty,
			"scraped_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
		}


def _extract_section_html(driver, md_block):
	"""Split .md content into section HTML chunks to preserve MathML/KaTeX markup."""
	sections = driver.execute_script(
		"""
		const root = arguments[0];
		const labels = new Set(["input", "output", "constraints", "example", "tags"]);
		const sections = { statement: [], input: [], output: [], constraints: [], example: [], tags: [] };
		let current = "statement";

		function normalize(text) {
			return (text || "").trim().toLowerCase().replace(/:\s*$/, "");
		}

		function labelFromNode(node) {
			if (!node || node.nodeType !== 1) return null;
			const text = normalize(node.textContent);
			if (labels.has(text)) return text;

			const strong = node.querySelector("strong");
			if (!strong) return null;
			const strongText = normalize(strong.textContent);
			if (labels.has(strongText) && strongText === text) {
				return strongText;
			}
			return null;
		}

		for (const child of root.children) {
			const label = labelFromNode(child);
			if (label) {
				current = label;
				continue;
			}
			sections[current].push(child.outerHTML);
		}

		for (const key of Object.keys(sections)) {
			sections[key] = sections[key].join("\\n").trim();
		}
		return sections;
		""",
		md_block,
	)
	return sections if isinstance(sections, dict) else {}


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
	section_html = _extract_section_html(driver, md_blocks[0])

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

	# Preserve section HTML so formulas and rich markup are not flattened to plain text.
	statement_html = (section_html.get("statement") or "").strip()
	input_html = (section_html.get("input") or "").strip()
	output_html = (section_html.get("output") or "").strip()
	constraints_html = (section_html.get("constraints") or "").strip()

	if statement_html:
		record.statement = statement_html
	if input_html:
		record.input_description = input_html
	if output_html:
		record.output_description = output_html
	if constraints_html:
		record.constraints_html = constraints_html

	# Scrape difficulty from stats page
	task_id = extract_task_id_from_url(problem_url)
	if task_id:
		stats = scrape_problem_stats(driver, task_id)
		record.difficulty = stats.get("difficulty", "medium")
		print(f"Problem {title}: success_rate={stats.get('success_rate', 0):.2f}%, difficulty={record.difficulty}")

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
	example_indices = {}
	
	for idx, line in enumerate(lines):
		if line in labels and line not in indices:
			indices[line] = idx
		# Detect Example 1, Example 2, etc. (numbered examples)
		if re.match(r"^Example\s*\d+$", line, re.IGNORECASE):
			example_indices[line] = idx
	
	# Store numbered examples in order (if any detected)
	if example_indices:
		indices["Examples"] = example_indices
	
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


def _extract_multiple_examples(lines, example_indices, tags_idx):
	"""Extract all numbered examples (Example 1, Example 2, etc.) from lines.
	
	Returns list of (input, output) tuples.
	"""
	examples = []
	sorted_examples = sorted(example_indices.items(), key=lambda x: x[1])
	
	for i, (example_label, start_idx) in enumerate(sorted_examples):
		# Find end of this example (start of next section or end of lines)
		if i + 1 < len(sorted_examples):
			end_idx = sorted_examples[i + 1][1]
		elif tags_idx is not None:
			end_idx = tags_idx
		else:
			end_idx = len(lines)
		
		example_lines = lines[start_idx + 1 : end_idx]
		example_input, example_output = _extract_example(example_lines)
		if example_input and example_output:
			examples.append((example_input, example_output))
	
	return examples


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
	required_sections = ["Input", "Output", "Constraints"]
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

	# Initialize example variables
	example_input = ""
	example_output = ""
	examples = []
	
	# Handle Examples (both single "Example" section and numbered "Example 1", "Example 2", etc.)
	tags_idx = indices.get("Tags")
	if "Examples" in indices and indices["Examples"]:
		# Multiple numbered examples (Example 1, Example 2, etc.)
		example_end = tags_idx if tags_idx else len(lines)
		constraints_lines = lines[indices["Constraints"] + 1 : min(indices["Examples"][list(indices["Examples"].keys())[0]], example_end)]
		tags_lines = lines[tags_idx + 1 :] if tags_idx else []
		examples = _extract_multiple_examples(lines, indices["Examples"], tags_idx)
		# Set first example as primary
		if examples:
			example_input, example_output = examples[0]
	elif "Example" in indices:
		# Single "Example" section
		example_end = tags_idx if tags_idx else len(lines)
		constraints_lines = lines[indices["Constraints"] + 1 : indices["Example"]]
		example_lines = lines[indices["Example"] + 1 : example_end]
		tags_lines = lines[tags_idx + 1 :] if tags_idx else []
		example_input, example_output = _extract_example(example_lines)
		examples = [(example_input, example_output)] if example_input and example_output else []
	else:
		# No example section
		example_end = tags_idx if tags_idx else len(lines)
		constraints_lines = lines[indices["Constraints"] + 1 : example_end]
		tags_lines = lines[tags_idx + 1 :] if tags_idx else []
	
	tags = [line.strip() for line in tags_lines if line.strip() and "show problem tags" not in line.lower()]

	record = ProblemRecord(
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
		examples=examples,
		tags=tags,
		source_url=source_url,
		slug=slugify(title),
	)
	
	return record














