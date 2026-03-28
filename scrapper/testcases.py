import os
import zipfile

from utils import ensure_dir, write_text_file


def build_testcase_artifacts(base_dir, slug, sample_input, sample_output):
	testcase_dir = ensure_dir(os.path.join(base_dir, "testcases", slug))
	input_path = os.path.join(testcase_dir, "input.txt")
	output_path = os.path.join(testcase_dir, "output.txt")

	write_text_file(input_path, (sample_input or "").strip() + "\n")
	write_text_file(output_path, (sample_output or "").strip() + "\n")

	return {
		"input_path": input_path,
		"output_path": output_path,
	}


def extract_zip_testcases(zip_path, base_dir, folder_name):
	testcase_dir = ensure_dir(os.path.join(base_dir, "testcases", folder_name))

	written_files = []
	with zipfile.ZipFile(zip_path, "r") as archive:
		for member in archive.namelist():
			normalized = member.replace("\\", "/")
			if not normalized.lower().endswith((".in", ".out")):
				continue

			filename = os.path.basename(normalized)
			if not filename:
				continue

			stem, ext = os.path.splitext(filename)
			if ext.lower() == ".in":
				out_name = f"{stem}-input.txt"
			else:
				out_name = f"{stem}-output.txt"

			target_path = os.path.join(testcase_dir, out_name)
			with archive.open(member, "r") as src, open(target_path, "wb") as dst:
				dst.write(src.read())
			written_files.append(target_path)

	return sorted(written_files)


def collect_testcase_pairs(testcase_paths):
	pairs = {}
	for path in testcase_paths:
		name = os.path.basename(path)
		lower = name.lower()

		if lower.endswith("-input.txt"):
			index = name[: -len("-input.txt")]
			pairs.setdefault(index, {})["input"] = path
			continue
		if lower.endswith("-output.txt"):
			index = name[: -len("-output.txt")]
			pairs.setdefault(index, {})["output"] = path
			continue

		# Backward-compatible fallback for old .in/.out files.
		stem, ext = os.path.splitext(name)
		ext = ext.lower()
		if ext == ".in":
			pairs.setdefault(stem, {})["input"] = path
		elif ext == ".out":
			pairs.setdefault(stem, {})["output"] = path

	def sort_key(item):
		key = item[0]
		return (0, int(key)) if key.isdigit() else (1, key)

	results = []
	for idx, files in sorted(pairs.items(), key=sort_key):
		if "input" in files and "output" in files:
			results.append(
				{
					"index": idx,
					"input_path": files["input"],
					"output_path": files["output"],
				}
			)

	return results




