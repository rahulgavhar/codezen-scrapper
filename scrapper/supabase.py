import json

import requests


def upload_bytes(supabase_url, supabase_key, bucket, object_path, content_bytes, content_type):
	endpoint = f"{supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{object_path.lstrip('/')}"
	headers = {
		"Authorization": f"Bearer {supabase_key}",
		"apikey": supabase_key,
		"x-upsert": "true",
		"Content-Type": content_type,
	}
	response = requests.post(endpoint, headers=headers, data=content_bytes, timeout=30)
	if response.status_code >= 400:
		raise RuntimeError(
			f"Supabase upload failed for {bucket}/{object_path}: "
			f"{response.status_code} {response.text}"
		)
	return response.json() if response.text else {"status": "ok"}


def upload_problem_json(supabase_url, supabase_key, bucket, object_path, payload):
	raw = json.dumps(payload, indent=2).encode("utf-8")
	return upload_bytes(
		supabase_url=supabase_url,
		supabase_key=supabase_key,
		bucket=bucket,
		object_path=object_path,
		content_bytes=raw,
		content_type="application/json",
	)


def upload_text_file(supabase_url, supabase_key, bucket, object_path, text):
	raw = text.encode("utf-8")
	return upload_bytes(
		supabase_url=supabase_url,
		supabase_key=supabase_key,
		bucket=bucket,
		object_path=object_path,
		content_bytes=raw,
		content_type="text/plain",
	)


def insert_problem_to_db(supabase_url, supabase_key, problem_data, created_by):
	"""Insert problem record into problems table"""
	endpoint = f"{supabase_url.rstrip('/')}/rest/v1/problems"
	
	payload = {
		"title": problem_data.get("title", ""),
		"slug": problem_data.get("slug", ""),
		"difficulty": "medium",  # Default, can be updated later
		"description": problem_data.get("statement_text", ""),
		"input_format": problem_data.get("input_section", ""),
		"output_format": problem_data.get("output_section", ""),
		"constraints": problem_data.get("constraints_text", ""),
		"time_limit_ms": _parse_time_limit(problem_data.get("time_limit", "")),
		"memory_limit_mb": _parse_memory_limit(problem_data.get("memory_limit", "")),
		"status": "published",
		"created_by": created_by,
		"source": "cses",
	}
	
	headers = {
		"Authorization": f"Bearer {supabase_key}",
		"apikey": supabase_key,
		"Content-Type": "application/json",
		"Prefer": "return=representation",
	}
	
	response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
	if response.status_code >= 400:
		raise RuntimeError(f"Failed to insert problem: {response.status_code} {response.text}")
	
	result = response.json()
	if isinstance(result, list) and len(result) > 0:
		return result[0]  # Return inserted record with ID
	return result


def insert_problem_sample_to_db(supabase_url, supabase_key, problem_id, sample_index, input_text, output_text):
	"""Insert sample testcase into problem_samples table"""
	endpoint = f"{supabase_url.rstrip('/')}/rest/v1/problem_samples"
	
	payload = {
		"problem_id": problem_id,
		"sample_index": sample_index,
		"input": input_text,
		"output": output_text,
	}
	
	headers = {
		"Authorization": f"Bearer {supabase_key}",
		"apikey": supabase_key,
		"Content-Type": "application/json",
		"Prefer": "return=representation",
	}
	
	response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
	if response.status_code >= 400:
		raise RuntimeError(f"Failed to insert sample: {response.status_code} {response.text}")
	
	return response.json()


def insert_test_case_set_to_db(supabase_url, supabase_key, problem_id, storage_bucket, input_path, output_path):
	"""Insert test case set reference into test_case_sets table"""
	endpoint = f"{supabase_url.rstrip('/')}/rest/v1/test_case_sets"
	
	payload = {
		"problem_id": problem_id,
		"storage_bucket": storage_bucket,
		"input_path": input_path,
		"output_path": output_path,
	}
	
	headers = {
		"Authorization": f"Bearer {supabase_key}",
		"apikey": supabase_key,
		"Content-Type": "application/json",
		"Prefer": "return=representation",
	}
	
	response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
	if response.status_code >= 400:
		raise RuntimeError(f"Failed to insert test case set: {response.status_code} {response.text}")
	
	return response.json()


def insert_problem_tags_to_db(supabase_url, supabase_key, problem_id, tags):
	"""Insert tags for a problem"""
	# First get or create tag IDs
	for tag_name in tags:
		tag_id = _get_or_create_tag(supabase_url, supabase_key, tag_name.lower())
		_link_tag_to_problem(supabase_url, supabase_key, problem_id, tag_id)


def _get_or_create_tag(supabase_url, supabase_key, tag_name):
	"""Get existing tag or create new one"""
	tag_name_lower = tag_name.lower()
	
	# Try to get existing tag
	endpoint = f"{supabase_url.rstrip('/')}/rest/v1/tags?name=eq.{tag_name_lower}"
	headers = {
		"Authorization": f"Bearer {supabase_key}",
		"apikey": supabase_key,
	}
	
	response = requests.get(endpoint, headers=headers, timeout=30)
	if response.status_code == 200:
		result = response.json()
		if result and len(result) > 0:
			return result[0]["id"]
	
	# Create new tag
	endpoint = f"{supabase_url.rstrip('/')}/rest/v1/tags"
	payload = {"name": tag_name_lower}
	
	headers["Content-Type"] = "application/json"
	headers["Prefer"] = "return=representation"
	
	response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
	if response.status_code >= 400:
		raise RuntimeError(f"Failed to create tag: {response.status_code} {response.text}")
	
	result = response.json()
	if isinstance(result, list) and len(result) > 0:
		return result[0]["id"]
	return result.get("id")


def _link_tag_to_problem(supabase_url, supabase_key, problem_id, tag_id):
	"""Link a tag to a problem in problem_tags junction table"""
	endpoint = f"{supabase_url.rstrip('/')}/rest/v1/problem_tags"
	
	payload = {
		"problem_id": problem_id,
		"tag_id": tag_id,
	}
	
	headers = {
		"Authorization": f"Bearer {supabase_key}",
		"apikey": supabase_key,
		"Content-Type": "application/json",
	}
	
	# Try to insert, ignore if already exists (duplicate key)
	response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
	if response.status_code >= 409:
		# Duplicate key, already linked
		return
	elif response.status_code >= 400:
		raise RuntimeError(f"Failed to link tag: {response.status_code} {response.text}")


def _parse_time_limit(time_limit_str):
	"""Parse time limit string (e.g., '1.00 s') to milliseconds"""
	import re
	match = re.search(r'([\d.]+)\s*s', time_limit_str or "2.00 s")
	if match:
		seconds = float(match.group(1))
		return int(seconds * 1000)
	return 2000  # Default 2 seconds


def _parse_memory_limit(memory_limit_str):
	"""Parse memory limit string (e.g., '512 MB') to MB"""
	import re
	match = re.search(r'(\d+)\s*MB', memory_limit_str or "256 MB")
	if match:
		return int(match.group(1))
	return 256  # Default 256 MB
