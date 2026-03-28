from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
import os
import time
import tempfile
import shutil
import json

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")



def _find_first(driver, selectors):
    for by, selector in selectors:
        matches = driver.find_elements(by, selector)
        if matches:
            return matches[0]
    return None


def _wait_for_zip(download_dir, start_ts, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        zip_files = []
        for name in os.listdir(download_dir):
            if not name.lower().endswith(".zip"):
                continue
            abs_path = os.path.join(download_dir, name)
            if os.path.getmtime(abs_path) >= start_ts - 1:
                zip_files.append(abs_path)

        if zip_files:
            latest = max(zip_files, key=os.path.getmtime)
            first_size = os.path.getsize(latest)
            time.sleep(1)
            second_size = os.path.getsize(latest)
            if first_size == second_size and not os.path.exists(latest + ".crdownload"):
                return latest

        time.sleep(1)

    raise TimeoutException("Timed out waiting for tests.zip download to complete.")


def login_cses(driver, username, password, timeout=25):
    driver.get("https://cses.fi/login")
    wait = WebDriverWait(driver, timeout)

    username_input = wait.until(
        lambda d: _find_first(
            d,
            [
                (By.NAME, "nick"),
                (By.NAME, "username"),
                (By.CSS_SELECTOR, "input[type='text']"),
            ],
        )
    )
    password_input = _find_first(
        driver,
        [
            (By.NAME, "pass"),
            (By.NAME, "password"),
            (By.CSS_SELECTOR, "input[type='password']"),
        ],
    )
    if password_input is None:
        raise RuntimeError("Could not find CSES password field on login page.")

    username_input.clear()
    username_input.send_keys(username)
    password_input.clear()
    password_input.send_keys(password)

    submit = _find_first(
        driver,
        [
            (By.CSS_SELECTOR, "button[type='submit']"),
            (By.CSS_SELECTOR, "input[type='submit']"),
            (By.XPATH, "//button[contains(., 'Login') or contains(., 'Sign in')]"),
        ],
    )
    if submit is not None:
        submit.click()
    else:
        password_input.send_keys(Keys.ENTER)

    wait.until(
        lambda d: _find_first(
            d,
            [
                (By.CSS_SELECTOR, "a[href*='logout']"),
                (By.XPATH, "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'logout')]"),
            ],
        )
        is not None
    )


def download_tests_zip(driver, tests_url, download_dir=DOWNLOAD_DIR, timeout=120):
    os.makedirs(download_dir, exist_ok=True)
    start_ts = time.time()
    driver.get(tests_url)
    time.sleep(1)

    link = _find_first(
        driver,
        [
            (By.CSS_SELECTOR, "a[href$='.zip']"),
            (By.CSS_SELECTOR, "input[type='submit'][value*='Download']"),
            (By.CSS_SELECTOR, "input[type='submit'][value*='download']"),
            (By.XPATH, "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download')]"),
            (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download')]"),
        ],
    )

    if link is not None:
        href = link.get_attribute("href")
        if href and href.lower().endswith(".zip"):
            driver.get(href)
        else:
            link.click()

    return _wait_for_zip(download_dir=download_dir, start_ts=start_ts, timeout=timeout)



def create_browser(
    headless=False,
    download_dir=DOWNLOAD_DIR,
    chrome_user_data_dir="",
    chrome_profile_dir="",
    extension_dir_path="",
    extension_crx_path="",
    extension_pem_path="",
):
    os.makedirs(download_dir, exist_ok=True)

    options = Options()
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )
    options.add_argument("--start-maximized")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-background-networking")
    options.add_argument("--remote-debugging-port=9222")
    
    # Enable WebDriver BiDi for runtime extension installation
    try:
        options.enable_bidi = True
    except Exception:
        pass
    
    if chrome_user_data_dir:
        options.add_argument(f"--user-data-dir={chrome_user_data_dir}")
    if chrome_profile_dir:
        options.add_argument(f"--profile-directory={chrome_profile_dir}")

    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    # Required for headless Chrome to persist downloads to disk.
    try:
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": download_dir},
        )
    except Exception:
        pass

    # Install extension via WebDriver BiDi (modern approach)
    extension_to_load = None
    if extension_dir_path:
        if not os.path.isdir(extension_dir_path):
            raise ValueError(f"Extension directory not found: {extension_dir_path}")
        manifest_path = os.path.join(extension_dir_path, "manifest.json")
        if not os.path.isfile(manifest_path):
            raise ValueError(f"Extension manifest.json not found: {extension_dir_path}")
        extension_to_load = extension_dir_path
    elif extension_crx_path:
        if not os.path.isfile(extension_crx_path):
            raise ValueError(f"Extension CRX file not found: {extension_crx_path}")
        extension_to_load = extension_crx_path

    if extension_to_load:
        try:
            # Try WebDriver BiDi approach (modern)
            abs_ext_path = os.path.abspath(extension_to_load)
            driver.install_addon(abs_ext_path)
            print(f"Extension installed via BiDi: {abs_ext_path}")
        except AttributeError:
            # WebDriver BiDi not available, try add_extension (deprecated but works as fallback)
            try:
                if os.path.isdir(extension_to_load):
                    # For unpacked extensions, use CDP to load
                    print(f"Installing unpacked extension: {extension_to_load}")
                    # Chrome requires loading unpacked extensions via command line
                    driver.quit()
                    options2 = Options()
                    options2.add_experimental_option(
                        "prefs",
                        {
                            "download.default_directory": download_dir,
                            "download.prompt_for_download": False,
                            "download.directory_upgrade": True,
                            "safebrowsing.enabled": True,
                        },
                    )
                    options2.add_argument("--start-maximized")
                    options2.add_argument("--no-first-run")
                    options2.add_argument("--no-default-browser-check")
                    options2.add_argument("--disable-background-networking")
                    options2.add_argument("--remote-debugging-port=9222")
                    abs_ext_path = os.path.abspath(extension_to_load)
                    options2.add_argument(f"--load-extension={abs_ext_path}")
                    if chrome_user_data_dir:
                        options2.add_argument(f"--user-data-dir={chrome_user_data_dir}")
                    if chrome_profile_dir:
                        options2.add_argument(f"--profile-directory={chrome_profile_dir}")
                    if headless:
                        options2.add_argument("--headless=new")
                        options2.add_argument("--disable-gpu")
                        options2.add_argument("--window-size=1920,1080")
                    
                    driver = webdriver.Chrome(
                        service=Service(ChromeDriverManager().install()),
                        options=options2
                    )
                    print(f"Extension loaded via command line: {abs_ext_path}")
                else:
                    # CRX file
                    driver.install_addon(extension_to_load)
                    print(f"Extension installed: {extension_to_load}")
            except Exception as e:
                print(f"Warning: Could not install extension: {e}")

    return driver
