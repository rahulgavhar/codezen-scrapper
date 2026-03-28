import json
import os
import re


SCRAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(SCRAPPER_DIR, "downloads")


def ensure_dir(path):
	os.makedirs(path, exist_ok=True)
	return path


def slugify(text):
	cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
	return cleaned.strip("-") or "problem"


def write_text_file(file_path, content):
	parent = os.path.dirname(file_path)
	if parent:
		ensure_dir(parent)
	with open(file_path, "w", encoding="utf-8", newline="\n") as handle:
		handle.write(content)


def write_json_file(file_path, payload):
	parent = os.path.dirname(file_path)
	if parent:
		ensure_dir(parent)
	with open(file_path, "w", encoding="utf-8", newline="\n") as handle:
		json.dump(payload, handle, indent=2, ensure_ascii=True)


def load_tags_from_json(task_id):
	"""Load tags for a specific task_id from tags.json"""
	tags_file = os.path.join(SCRAPPER_DIR, "tags.json")
	
	if not os.path.isfile(tags_file):
		return []
	
	try:
		with open(tags_file, "r", encoding="utf-8") as handle:
			tags_data = json.load(handle)
	except (json.JSONDecodeError, IOError):
		return []
	
	# Support both formats: {"task_id": "tags"} or {"task_id": ["tag1", "tag2"]}
	if isinstance(tags_data, dict):
		tags = tags_data.get(str(task_id), [])
		if isinstance(tags, str):
			return [tags] if tags else []
		elif isinstance(tags, list):
			return tags
	
	return []
