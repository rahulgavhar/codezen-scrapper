import os
from getpass import getpass


_ENV_LOADED = False


def _parse_env_line(line):
	if "=" not in line:
		return None, None
	key, value = line.split("=", 1)
	key = key.strip()
	value = value.strip()
	if value.startswith(('"', "'")) and value.endswith(('"', "'")) and len(value) >= 2:
		value = value[1:-1]
	return key, value


def _load_env_file_if_present():
	global _ENV_LOADED
	if _ENV_LOADED:
		return

	search_paths = [
		os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
		os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
	]

	for env_path in search_paths:
		if not os.path.exists(env_path):
			continue
		with open(env_path, "r", encoding="utf-8") as handle:
			for raw_line in handle:
				line = raw_line.strip()
				if not line or line.startswith("#"):
					continue
				key, value = _parse_env_line(line)
				if key:
					os.environ.setdefault(key, value)

	_ENV_LOADED = True


def load_bucket_names():
	_load_env_file_if_present()
	problems_bucket = os.getenv("SUPABASE_STORAGE_PROBLEMS_BUCKET", "problems").strip() or "problems"
	testcases_bucket = os.getenv("SUPABASE_STORAGE_TESTCASES_BUCKET", "testcases").strip() or "testcases"
	return problems_bucket, testcases_bucket


def load_cses_credentials(username_arg="", password_arg="", prompt_if_missing=False):
	_load_env_file_if_present()
	username = (username_arg or os.getenv("CSES_USERNAME", "")).strip()
	password = (password_arg or os.getenv("CSES_PASSWORD", "")).strip()

	if prompt_if_missing and username and not password:
		password = getpass("Enter CSES password: ").strip()

	if not username or not password:
		raise ValueError(
			"Missing CSES credentials. Set CSES_USERNAME and CSES_PASSWORD in .env or pass --cses-username/--cses-password."
		)

	return username, password


def load_supabase_credentials():
    _load_env_file_if_present()
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_ANON_KEY", "").strip()
        or os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
    )

    if not supabase_url or not supabase_key:
        raise ValueError(
            "Missing SUPABASE_URL and a usable key. Set SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY."
        )

    return supabase_url, supabase_key


def load_scraper_user_id():
	"""Load the default Clerk user ID for the CSES scraper from environment"""
	_load_env_file_if_present()
	user_id = os.getenv("SCRAPER_CLERK_USER_ID", "").strip()
	
	if not user_id:
		raise ValueError(
			"Missing SCRAPER_CLERK_USER_ID in .env file. "
			"This is required for database operations."
		)
	
	return user_id
